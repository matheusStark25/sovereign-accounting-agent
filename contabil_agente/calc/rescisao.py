"""Rescisão do contrato de trabalho (CLT): verbas, descontos, FGTS e explicação.

Regras implementadas (conferir com o contador em casos especiais):

* Aviso prévio proporcional: 30 dias + 3 dias por ano completo, máximo 90 (Lei 12.506/2011).
* Aviso indenizado projeta o tempo de serviço para férias proporcionais e 13º (TST, Súmula 371).
* Férias vencidas e proporcionais indenizadas, com 1/3 constitucional, e aviso indenizado
  não sofrem INSS nem IRRF; saldo de salário sofre ambos.
* 13º salário: INSS e IRRF calculados à parte, sobre o valor total do 13º.
* Justa causa: saldo de salário e férias vencidas (+1/3). Sem 13º, férias proporcionais, aviso nem multa.
* Pedido de demissão: sem aviso indenizado nem multa; aviso não cumprido pode ser descontado (CLT 487, §2º).
* Acordo (CLT 484-A): metade do aviso indenizado, multa de 20% e saque de 80% do FGTS.
* A multa do FGTS só é calculada com o saldo informado; sem saldo, vira pendência (nunca é estimada).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from . import datas
from .errors import DadosInvalidos, TipoNaoSuportado
from .inss import calcular_inss
from .irrf import calcular_irrf_mensal
from .money import ZERO, D, nao_negativo, q2
from .tables import tabela_inss, tabela_irrf

TIPOS = ("sem_justa_causa", "justa_causa", "pedido_demissao", "acordo")

_SINONIMOS_TIPO = {
    "sem_justa_causa": "sem_justa_causa",
    "sem justa causa": "sem_justa_causa",
    "demissao": "sem_justa_causa",
    "demissão": "sem_justa_causa",
    "dispensa": "sem_justa_causa",
    "justa_causa": "justa_causa",
    "justa causa": "justa_causa",
    "pedido_demissao": "pedido_demissao",
    "pedido de demissao": "pedido_demissao",
    "pedido de demissão": "pedido_demissao",
    "pedido": "pedido_demissao",
    "acordo": "acordo",
    "acordo mutuo": "acordo",
    "acordo mútuo": "acordo",
    "comum acordo": "acordo",
}

_OITO_POR_CENTO = Decimal("0.08")


def ler_data(valor: Any, campo: str) -> date:
    """Aceita date, 'AAAA-MM-DD' e 'DD/MM/AAAA'."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(texto, formato).date()
            except ValueError:
                continue
    raise DadosInvalidos(f"{campo}: informe a data no formato DD/MM/AAAA (recebi {valor!r})")


@dataclass
class DadosRescisao:
    tipo: str
    data_admissao: date
    data_demissao: date
    salario_base: Decimal
    aviso_previo: Optional[str] = None  # trabalhado | indenizado | nao_cumprido
    adicionais_mensais: Decimal = ZERO  # periculosidade, insalubridade etc. (valor mensal)
    media_variaveis: Decimal = ZERO  # média de horas extras/comissões (base de aviso, férias e 13º)
    variaveis_mes: Decimal = ZERO  # variáveis do mês da rescisão (somam ao saldo de salário)
    dependentes_irrf: int = 0
    pensao_alimenticia: Decimal = ZERO
    saldo_fgts: Optional[Decimal] = None  # do extrato; sem ele a multa fica pendente
    periodos_ferias_vencidas: int = 0
    periodos_ferias_vencidas_em_dobro: int = 0
    adiantamento_13: Decimal = ZERO  # 13º já pago (1ª parcela)
    base_inss_ja_paga_no_mes: Decimal = ZERO

    def normalizado(self) -> "DadosRescisao":
        tipo = _SINONIMOS_TIPO.get(str(self.tipo).strip().lower())
        if tipo is None:
            raise TipoNaoSuportado(
                f"Tipo de rescisão não suportado: {self.tipo!r}. Use: {', '.join(TIPOS)}."
            )
        adm = ler_data(self.data_admissao, "data de admissão")
        dem = ler_data(self.data_demissao, "data de demissão")
        if dem < adm:
            raise DadosInvalidos("A data de demissão não pode ser anterior à admissão.")
        salario = D(self.salario_base, "salário base")
        if salario <= 0:
            raise DadosInvalidos("O salário base deve ser maior que zero.")
        aviso = None if self.aviso_previo is None else str(self.aviso_previo).strip().lower()
        if tipo in ("sem_justa_causa", "acordo"):
            if aviso not in ("trabalhado", "indenizado"):
                raise DadosInvalidos("Informe se o aviso prévio foi 'trabalhado' ou 'indenizado'.")
        elif tipo == "pedido_demissao":
            if aviso not in ("trabalhado", "nao_cumprido"):
                raise DadosInvalidos("No pedido de demissão, informe o aviso: 'trabalhado' ou 'nao_cumprido'.")
        else:
            aviso = None
        dependentes = int(self.dependentes_irrf)
        if dependentes < 0:
            raise DadosInvalidos("Número de dependentes não pode ser negativo.")
        for nome in ("periodos_ferias_vencidas", "periodos_ferias_vencidas_em_dobro"):
            if int(getattr(self, nome)) < 0:
                raise DadosInvalidos(f"{nome} não pode ser negativo.")
        return DadosRescisao(
            tipo=tipo,
            data_admissao=adm,
            data_demissao=dem,
            salario_base=salario,
            aviso_previo=aviso,
            adicionais_mensais=nao_negativo(D(self.adicionais_mensais, "adicionais"), "adicionais"),
            media_variaveis=nao_negativo(D(self.media_variaveis, "média de variáveis"), "média de variáveis"),
            variaveis_mes=nao_negativo(D(self.variaveis_mes, "variáveis do mês"), "variáveis do mês"),
            dependentes_irrf=dependentes,
            pensao_alimenticia=nao_negativo(D(self.pensao_alimenticia, "pensão"), "pensão"),
            saldo_fgts=None
            if self.saldo_fgts is None
            else nao_negativo(D(self.saldo_fgts, "saldo do FGTS"), "saldo do FGTS"),
            periodos_ferias_vencidas=int(self.periodos_ferias_vencidas),
            periodos_ferias_vencidas_em_dobro=int(self.periodos_ferias_vencidas_em_dobro),
            adiantamento_13=nao_negativo(D(self.adiantamento_13, "adiantamento de 13º"), "adiantamento de 13º"),
            base_inss_ja_paga_no_mes=nao_negativo(
                D(self.base_inss_ja_paga_no_mes, "base de INSS já paga no mês"), "base de INSS já paga no mês"
            ),
        )


def dados_de_dict(payload: Dict[str, Any]) -> DadosRescisao:
    """Monta DadosRescisao a partir de um dicionário (chat, API ou JSON)."""
    def pegar(*nomes, padrao=None):
        for nome in nomes:
            if payload.get(nome) not in (None, ""):
                return payload[nome]
        return padrao

    faltando = [
        rotulo
        for rotulo, nomes in (
            ("tipo da rescisão", ("tipo", "tipo_rescisao")),
            ("data de admissão", ("data_admissao", "admissao")),
            ("data de demissão", ("data_demissao", "demissao")),
            ("salário", ("salario_base", "salario")),
        )
        if pegar(*nomes) is None
    ]
    if faltando:
        raise DadosInvalidos("Faltam dados para calcular a rescisão: " + ", ".join(faltando) + ".")
    return DadosRescisao(
        tipo=pegar("tipo", "tipo_rescisao"),
        data_admissao=pegar("data_admissao", "admissao"),
        data_demissao=pegar("data_demissao", "demissao"),
        salario_base=pegar("salario_base", "salario"),
        aviso_previo=pegar("aviso_previo", "aviso"),
        adicionais_mensais=pegar("adicionais_mensais", "adicionais", padrao=0),
        media_variaveis=pegar("media_variaveis", padrao=0),
        variaveis_mes=pegar("variaveis_mes", padrao=0),
        dependentes_irrf=pegar("dependentes_irrf", "dependentes", padrao=0),
        pensao_alimenticia=pegar("pensao_alimenticia", "pensao", padrao=0),
        saldo_fgts=pegar("saldo_fgts"),
        periodos_ferias_vencidas=pegar("periodos_ferias_vencidas", "ferias_vencidas", padrao=0),
        periodos_ferias_vencidas_em_dobro=pegar("periodos_ferias_vencidas_em_dobro", padrao=0),
        adiantamento_13=pegar("adiantamento_13", padrao=0),
        base_inss_ja_paga_no_mes=pegar("base_inss_ja_paga_no_mes", padrao=0),
    )


@dataclass(frozen=True)
class Verba:
    codigo: str
    descricao: str
    valor: Decimal
    incide_inss: bool
    incide_irrf: bool
    base_legal: str
    memoria: str


@dataclass(frozen=True)
class Desconto:
    codigo: str
    descricao: str
    valor: Decimal
    memoria: str


@dataclass
class ResultadoRescisao:
    dados: DadosRescisao
    verbas: Tuple[Verba, ...]
    descontos: Tuple[Desconto, ...]
    total_proventos: Decimal
    total_descontos: Decimal
    liquido: Decimal
    fgts: Dict[str, Any]
    direitos: Dict[str, Any]
    datas: Dict[str, Any]
    tabelas: Dict[str, str]
    explicacao: List[str] = field(default_factory=list)
    pendencias: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Dicionário serializável em JSON (valores monetários como float com 2 casas)."""
        def f(x):
            return None if x is None else float(q2(x))

        return {
            "status": "success",
            "tipo": self.dados.tipo,
            "datas": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.datas.items()},
            "verbas": [
                {
                    "codigo": v.codigo,
                    "descricao": v.descricao,
                    "valor": f(v.valor),
                    "incide_inss": v.incide_inss,
                    "incide_irrf": v.incide_irrf,
                    "base_legal": v.base_legal,
                    "memoria": v.memoria,
                }
                for v in self.verbas
            ],
            "descontos": [
                {"codigo": d.codigo, "descricao": d.descricao, "valor": f(d.valor), "memoria": d.memoria}
                for d in self.descontos
            ],
            "total_proventos": f(self.total_proventos),
            "total_descontos": f(self.total_descontos),
            "total_liquido": f(self.liquido),
            "fgts": {k: (f(v) if isinstance(v, Decimal) else v) for k, v in self.fgts.items()},
            "direitos": self.direitos,
            "tabelas": self.tabelas,
            "explicacao": self.explicacao,
            "pendencias": self.pendencias,
            "avisos": self.avisos,
        }


def _reais(valor: Decimal) -> str:
    inteiro, _, dec = f"{q2(valor):,.2f}".partition(".")
    return "R$ " + inteiro.replace(",", ".") + "," + dec


def calcular_rescisao(dados: DadosRescisao, caminho_tabelas: Optional[str] = None) -> ResultadoRescisao:
    dados = dados.normalizado()
    tipo = dados.tipo
    adm, dem = dados.data_admissao, dados.data_demissao
    competencia = date(dem.year, dem.month, 1)
    explic: List[str] = []
    pend: List[str] = []
    avisos: List[str] = []
    verbas: List[Verba] = []
    descontos: List[Desconto] = []

    # remunerações-base
    rem_fixa = dados.salario_base + dados.adicionais_mensais
    rem_base = rem_fixa + dados.media_variaveis
    explic.append(
        f"Remuneração-base: salário {_reais(dados.salario_base)} + adicionais {_reais(dados.adicionais_mensais)}"
        f" + média de variáveis {_reais(dados.media_variaveis)} = {_reais(rem_base)}."
    )

    # --- saldo de salário
    dias_mes = min(30, dem.day)
    saldo = q2(rem_fixa / 30 * dias_mes + dados.variaveis_mes)
    verbas.append(
        Verba("saldo_salario", f"Saldo de salário ({dias_mes} dias)", saldo, True, True, "CLT art. 477",
              f"({_reais(rem_fixa)} / 30) x {dias_mes} dias" + (f" + variáveis do mês {_reais(dados.variaveis_mes)}" if dados.variaveis_mes else ""))
    )

    # --- aviso prévio
    anos = datas.anos_completos(adm, dem)
    dias_aviso_total = min(90, 30 + 3 * anos)
    aviso_indenizado = ZERO
    dias_projecao = 0
    if tipo == "sem_justa_causa" and dados.aviso_previo == "indenizado":
        aviso_indenizado = q2(rem_base / 30 * dias_aviso_total)
        dias_projecao = dias_aviso_total
        verbas.append(
            Verba("aviso_previo", f"Aviso prévio indenizado ({dias_aviso_total} dias)", aviso_indenizado, False, False,
                  "Lei 12.506/2011; Lei 8.212/91 art. 28 §9º; Lei 7.713/88 art. 6º, V",
                  f"({_reais(rem_base)} / 30) x {dias_aviso_total} dias (30 + 3 x {anos} anos completos)")
        )
    elif tipo == "acordo" and dados.aviso_previo == "indenizado":
        aviso_indenizado = q2(rem_base / 30 * dias_aviso_total / 2)
        dias_projecao = dias_aviso_total // 2
        verbas.append(
            Verba("aviso_previo", f"Aviso prévio indenizado, metade ({dias_aviso_total} dias / 2)", aviso_indenizado, False, False,
                  "CLT art. 484-A, I, a", f"({_reais(rem_base)} / 30) x {dias_aviso_total} dias x 50%")
        )
        avisos.append(
            "Acordo (art. 484-A): a projeção do aviso sobre férias e 13º foi feita sobre metade dos dias do aviso. "
            "Há divergência de entendimento; confirme com seu contador."
        )
    elif tipo == "pedido_demissao" and dados.aviso_previo == "nao_cumprido":
        desconto_aviso = q2(rem_base)
        descontos.append(
            Desconto("aviso_nao_cumprido", "Desconto do aviso prévio não cumprido", desconto_aviso,
                     "CLT art. 487, §2º: salário correspondente ao prazo do aviso (30 dias)")
        )
    fim_projetado = dem + timedelta(days=dias_projecao)

    # --- 13º salário proporcional
    valor_13 = ZERO
    if tipo != "justa_causa":
        ano = dem.year
        meses_13 = datas.meses_de_13o_no_ano(adm, min(fim_projetado, date(ano, 12, 31)), ano)
        if fim_projetado.year > ano:
            meses_13 += datas.meses_de_13o_no_ano(date(ano + 1, 1, 1), fim_projetado, ano + 1)
        valor_13 = q2(rem_base / 12 * meses_13)
        verbas.append(
            Verba("decimo_terceiro", f"13º salário proporcional ({meses_13}/12)", valor_13, True, True,
                  "Lei 4.090/1962; Lei 4.749/1965", f"({_reais(rem_base)} / 12) x {meses_13} meses")
        )

    # --- férias vencidas
    valor_periodo = rem_base + rem_base / 3
    if dados.periodos_ferias_vencidas:
        valor = q2(valor_periodo * dados.periodos_ferias_vencidas)
        verbas.append(
            Verba("ferias_vencidas", f"Férias vencidas + 1/3 ({dados.periodos_ferias_vencidas} período(s))", valor, False, False,
                  "CLT arts. 129-145; Lei 8.212/91 art. 28 §9º, d",
                  f"({_reais(rem_base)} + 1/3) x {dados.periodos_ferias_vencidas}")
        )
    if dados.periodos_ferias_vencidas_em_dobro:
        valor = q2(valor_periodo * 2 * dados.periodos_ferias_vencidas_em_dobro)
        verbas.append(
            Verba("ferias_vencidas_dobro", f"Férias vencidas em dobro + 1/3 ({dados.periodos_ferias_vencidas_em_dobro} período(s))",
                  valor, False, False, "CLT art. 137", f"({_reais(rem_base)} + 1/3) x 2 x {dados.periodos_ferias_vencidas_em_dobro}")
        )
    avisos.append(
        f"Férias vencidas consideradas: {dados.periodos_ferias_vencidas} período(s) "
        f"e {dados.periodos_ferias_vencidas_em_dobro} em dobro. Informe se houver outros."
    )

    # --- férias proporcionais
    if tipo != "justa_causa":
        inicio_periodo = datas.inicio_periodo_aquisitivo(adm, fim_projetado)
        meses_ferias = min(12, datas.meses_com_fracao(inicio_periodo, fim_projetado))
        fp = q2(rem_base / 12 * meses_ferias)
        terco = q2(fp / 3)
        verbas.append(
            Verba("ferias_proporcionais", f"Férias proporcionais ({meses_ferias}/12)", fp, False, False,
                  "CLT art. 146, p.u.; TST Súmula 261",
                  f"({_reais(rem_base)} / 12) x {meses_ferias} meses (período aquisitivo desde {inicio_periodo:%d/%m/%Y})")
        )
        verbas.append(
            Verba("ferias_proporcionais_terco", "1/3 constitucional sobre férias proporcionais", terco, False, False,
                  "CF art. 7º, XVII", f"{_reais(fp)} / 3")
        )

    # --- encargos
    tab_inss = tabela_inss(competencia, caminho_tabelas)
    tab_irrf = tabela_irrf(competencia, caminho_tabelas)
    ja_paga = dados.base_inss_ja_paga_no_mes
    inss_saldo = calcular_inss(ja_paga + saldo, competencia, caminho_tabelas).valor
    if ja_paga > 0:
        inss_saldo -= calcular_inss(ja_paga, competencia, caminho_tabelas).valor
    irrf_saldo = calcular_irrf_mensal(
        saldo, competencia, inss=inss_saldo, dependentes=dados.dependentes_irrf,
        pensao_alimenticia=dados.pensao_alimenticia, caminho_tabelas=caminho_tabelas,
    )
    descontos.append(Desconto("inss_saldo", "INSS sobre o saldo de salário", inss_saldo,
                              f"base {_reais(saldo)}, tabela {tab_inss.vigencia_inicio:%Y}"))
    descontos.append(Desconto("irrf_saldo", "IRRF sobre o saldo de salário", irrf_saldo.valor,
                              f"base {_reais(irrf_saldo.base_calculo)} ({irrf_saldo.opcao_deducao}), imposto {_reais(irrf_saldo.imposto_tabela)}, redução {_reais(irrf_saldo.reducao)}"))
    if valor_13 > 0:
        inss_13 = calcular_inss(valor_13, competencia, caminho_tabelas).valor
        irrf_13 = calcular_irrf_mensal(
            valor_13, competencia, inss=inss_13, dependentes=dados.dependentes_irrf, caminho_tabelas=caminho_tabelas,
        )
        descontos.append(Desconto("inss_13", "INSS sobre o 13º salário (à parte)", inss_13, f"base {_reais(valor_13)}"))
        descontos.append(Desconto("irrf_13", "IRRF sobre o 13º salário (exclusivo na fonte)", irrf_13.valor,
                                  f"base {_reais(irrf_13.base_calculo)} ({irrf_13.opcao_deducao}), imposto {_reais(irrf_13.imposto_tabela)}, redução {_reais(irrf_13.reducao)}"))
    if dados.adiantamento_13 > 0:
        descontos.append(Desconto("adiantamento_13", "Adiantamento de 13º já pago", dados.adiantamento_13, "1ª parcela"))
    if dados.pensao_alimenticia > 0:
        descontos.append(Desconto("pensao", "Pensão alimentícia", dados.pensao_alimenticia, "repassada ao beneficiário"))

    # --- FGTS
    base_fgts = saldo + aviso_indenizado + valor_13
    fgts_rescisorio = q2(_OITO_POR_CENTO * base_fgts)
    aliquota_multa = {"sem_justa_causa": Decimal("0.40"), "acordo": Decimal("0.20")}.get(tipo, ZERO)
    multa: Optional[Decimal] = None
    if aliquota_multa > 0:
        if dados.saldo_fgts is None:
            pend.append(
                "Informe o saldo do FGTS (do extrato) para calcular a multa rescisória. "
                "O motor não estima esse valor."
            )
        else:
            multa = q2((dados.saldo_fgts + fgts_rescisorio) * aliquota_multa)
    else:
        multa = ZERO
    fgts = {
        "deposito_rescisorio": fgts_rescisorio,
        "base_deposito": base_fgts,
        "saldo_informado": dados.saldo_fgts,
        "multa_aliquota": float(aliquota_multa),
        "multa": multa,
    }
    direitos = {
        "saque_fgts_percentual": {"sem_justa_causa": 100, "acordo": 80}.get(tipo, 0),
        "seguro_desemprego": tipo == "sem_justa_causa",
        "observacao_seguro_desemprego": "Sujeito aos requisitos legais (tempo de trabalho e carência).",
    }

    # --- totais
    proventos = sum((v.valor for v in verbas), ZERO)
    total_descontos = sum((d.valor for d in descontos), ZERO)
    liquido = proventos - total_descontos
    if liquido < 0:
        avisos.append("Os descontos superam os proventos: há saldo devedor do trabalhador. Revise os dados.")

    # --- explicação e avisos fixos
    for v in verbas:
        explic.append(f"{v.descricao}: {_reais(v.valor)} = {v.memoria}.")
    for d in descontos:
        explic.append(f"{d.descricao}: {_reais(d.valor)} ({d.memoria}).")
    avisos.append(
        "IRRF: usa a opção mais vantajosa entre as deduções legais e o desconto simplificado, "
        "e a redução do art. 3º-A da Lei 9.250/1995 quando aplicável."
    )
    avisos.append(
        "Aviso prévio indenizado, férias indenizadas e 1/3 não sofrem INSS nem IRRF; o 13º é tributado à parte. "
        "Entendimento da legislação vigente: confirme com seu contador em casos especiais."
    )
    for nome, tab in (("INSS", tab_inss), ("IRRF", tab_irrf)):
        if tab.verificacao != "primaria":
            avisos.append(f"Tabela de {nome}: verificação '{tab.verificacao}' ({tab.norma}).")

    return ResultadoRescisao(
        dados=dados,
        verbas=tuple(verbas),
        descontos=tuple(descontos),
        total_proventos=proventos,
        total_descontos=total_descontos,
        liquido=liquido,
        fgts=fgts,
        direitos=direitos,
        datas={
            "admissao": adm,
            "demissao": dem,
            "anos_completos": anos,
            "dias_aviso_total": dias_aviso_total,
            "dias_projecao_aviso": dias_projecao,
            "fim_projetado": fim_projetado,
            "competencia": f"{competencia:%Y-%m}",
        },
        tabelas={
            "inss": f"{tab_inss.norma} [{tab_inss.verificacao}]",
            "irrf": f"{tab_irrf.norma} [{tab_irrf.verificacao}]",
        },
        explicacao=explic,
        pendencias=pend,
        avisos=avisos,
    )
