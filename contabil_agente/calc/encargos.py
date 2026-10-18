"""Encargos de quem não é empregado CLT: pró-labore, GPS, DAS do MEI e DARF em atraso.

Mesmas regras do resto do motor: ``Decimal`` em tudo, tabela oficial por competência (salário mínimo e teto do INSS vêm de
``calc/data/tabelas.yaml``) e **nada de estimar**: se falta um dado externo (a taxa SELIC acumulada do DARF, por exemplo) o
cálculo devolve ``FaltamDados`` com a pergunta a fazer.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .errors import CalculoError, DadosInvalidos
from .irrf import calcular_irrf_mensal
from .money import ZERO, D, nao_negativo, q2
from .rescisao import ler_data
from .tables import tabela_inss


class FaltamDados(CalculoError):
    """Falta um dado que o motor não pode inventar: ``faltando`` diz quais e ``pergunta`` como pedir."""

    def __init__(self, faltando: List[str], pergunta: str):
        super().__init__(pergunta)
        self.faltando, self.pergunta = faltando, pergunta


def _competencia_str(competencia: date) -> str:
    return f"{competencia:%Y-%m}"


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - nome do algoritmo
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_nacionais(ano: int) -> set:
    """Feriados nacionais (leis federais): datas fixas e Sexta-feira Santa. Estaduais, municipais, Carnaval e Corpus Christi não entram."""
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    return {date(ano, m, d) for m, d in fixos} | {_pascoa(ano) - timedelta(days=2)}


def _proximo_dia_util(d: date) -> date:
    """Próximo dia sem fim de semana nem feriado nacional (feriados estaduais e municipais não entram: o aviso do resultado diz isso)."""
    while d.weekday() >= 5 or d in feriados_nacionais(d.year):
        d += timedelta(days=1)
    return d


def _vencimento_no_mes_seguinte(competencia: date, dia: int) -> date:
    ano, mes = (competencia.year + 1, 1) if competencia.month == 12 else (competencia.year, competencia.month + 1)
    return _proximo_dia_util(date(ano, mes, dia))


# ---------------------------------------------------------------------------------------------------- pró-labore
ALIQUOTA_INSS_SOCIO = Decimal("0.11")  # Lei 10.666/2003, art. 4º: a empresa desconta 11% do contribuinte individual
ALIQUOTA_PATRONAL = Decimal("0.20")  # Lei 8.212/1991, art. 22, III
REGIMES = {
    "simples": "Simples Nacional (anexos I, II, III e V)",
    "simples_anexo_iv": "Simples Nacional, anexo IV",
    "presumido": "Lucro presumido",
    "real": "Lucro real",
}


def calcular_prolabore(prolabore, competencia: date, regime: str = "simples", dependentes: int = 0, caminho_tabelas: Optional[str] = None) -> Dict[str, Any]:
    """Pró-labore de sócio: INSS do sócio (11%, base entre 1 salário mínimo e o teto), IRRF e custo da empresa."""
    valor = nao_negativo(D(prolabore, "pró-labore"), "pró-labore")
    if valor <= 0:
        raise DadosInvalidos("pró-labore: informe um valor maior que zero")
    regime = (regime or "simples").strip().lower()
    if regime not in REGIMES:
        raise DadosInvalidos(f"regime: use um de {', '.join(REGIMES)} (recebi {regime!r})")
    t = tabela_inss(competencia, caminho_tabelas)
    base = min(max(valor, t.salario_minimo), t.teto)
    inss_socio = q2(base * ALIQUOTA_INSS_SOCIO)
    irrf = calcular_irrf_mensal(valor, competencia, inss=inss_socio, dependentes=dependentes, caminho_tabelas=caminho_tabelas)
    patronal = ZERO if regime == "simples" else q2(valor * ALIQUOTA_PATRONAL)

    avisos: List[str] = []
    if valor < t.salario_minimo:
        avisos.append(
            f"Pró-labore abaixo do salário mínimo ({t.salario_minimo}): o INSS do sócio incide sobre, no mínimo, 1 salário mínimo."
        )
    if valor > t.teto:
        avisos.append(f"INSS do sócio limitado ao teto de {t.teto}.")
    if regime == "simples":
        avisos.append("No Simples Nacional (anexos I, II, III e V) a contribuição patronal já está dentro do DAS: não há 20% à parte.")
    else:
        avisos.append("Contribuição patronal de 20% sobre o pró-labore; RAT/FAP e contribuições a terceiros não estão incluídos.")
    if dependentes:
        avisos.append(f"IRRF com {dependentes} dependente(s).")
    return {
        "status": "success",
        "regime": REGIMES[regime],
        "prolabore": float(q2(valor)),
        "base_inss_socio": float(q2(base)),
        "inss_socio": float(inss_socio),
        "irrf": float(irrf.valor),
        "liquido": float(q2(valor - inss_socio - irrf.valor)),
        "inss_patronal": float(patronal),
        "custo_total_empresa": float(q2(valor + patronal)),
        "avisos": avisos,
        "tabelas": {"inss": f"{t.norma} [{t.verificacao}]", "irrf": f"{irrf.norma} [{irrf.verificacao}]"},
        "competencia": _competencia_str(competencia),
    }


# ---------------------------------------------------------------------------------------------------------- GPS
TIPOS_GPS = {
    "contribuinte_individual": ("Contribuinte individual (plano normal)", Decimal("0.20"), True),
    "facultativo": ("Segurado facultativo (plano normal)", Decimal("0.20"), True),
    "plano_simplificado": ("Plano simplificado de previdência social", Decimal("0.11"), False),
    "baixa_renda": ("Facultativo de baixa renda", Decimal("0.05"), False),
}


def calcular_gps(tipo: str, competencia: date, base=None, caminho_tabelas: Optional[str] = None) -> Dict[str, Any]:
    """GPS de quem recolhe sozinho: 20% (base entre 1 salário mínimo e o teto), 11% e 5% (sobre o salário mínimo)."""
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS_GPS:
        raise DadosInvalidos(f"tipo da GPS: use um de {', '.join(TIPOS_GPS)} (recebi {tipo!r})")
    nome, aliquota, usa_base = TIPOS_GPS[tipo]
    t = tabela_inss(competencia, caminho_tabelas)
    avisos: List[str] = []
    if usa_base:
        if base in (None, ""):
            raise FaltamDados(["base"], "Para calcular a GPS, preciso do valor sobre o qual a contribuição incide (remuneração ou salário de contribuição).")
        informado = nao_negativo(D(base, "base"), "base")
        usada = min(max(informado, t.salario_minimo), t.teto)
        if usada != informado:
            avisos.append(f"Base ajustada para o limite {'mínimo' if usada > informado else 'máximo'} de {usada} (salário mínimo e teto do INSS).")
    else:
        usada = t.salario_minimo
        avisos.append(f"Alíquota de {aliquota * 100:.0f}% sobre 1 salário mínimo ({usada}).")
    vencimento = _vencimento_no_mes_seguinte(competencia, 15)
    avisos.append("Vencimento no dia 15 do mês seguinte; se não houver expediente bancário, pague no dia útil seguinte (aqui entram só fim de semana e feriados nacionais, não os estaduais e municipais).")
    return {
        "status": "success",
        "tipo": nome,
        "base": float(q2(usada)),
        "aliquota": float(aliquota),
        "valor": float(q2(usada * aliquota)),
        "vencimento": vencimento.isoformat(),
        "avisos": avisos,
        "tabela": f"{t.norma} [{t.verificacao}]",
        "competencia": _competencia_str(competencia),
    }


# ----------------------------------------------------------------------------------------------------- DAS do MEI
ICMS_MEI = Decimal("1.00")
ISS_MEI = Decimal("5.00")
ATIVIDADES_MEI = {
    "comercio": ("Comércio ou indústria", ICMS_MEI, ZERO, Decimal("0.05")),
    "servicos": ("Prestação de serviços", ZERO, ISS_MEI, Decimal("0.05")),
    "comercio_e_servicos": ("Comércio e serviços", ICMS_MEI, ISS_MEI, Decimal("0.05")),
    "caminhoneiro": ("MEI caminhoneiro", ICMS_MEI, ZERO, Decimal("0.12")),
}


def calcular_das_mei(atividade: str, competencia: date, caminho_tabelas: Optional[str] = None) -> Dict[str, Any]:
    """DAS mensal do MEI: INSS (5% do salário mínimo; 12% para caminhoneiro) + ICMS (R$ 1) e/ou ISS (R$ 5)."""
    chave = (atividade or "").strip().lower().replace(" ", "_")
    if chave == "industria":
        chave = "comercio"
    if chave not in ATIVIDADES_MEI:
        raise DadosInvalidos(f"atividade do MEI: use uma de {', '.join(ATIVIDADES_MEI)} (recebi {atividade!r})")
    nome, icms, iss, aliquota = ATIVIDADES_MEI[chave]
    t = tabela_inss(competencia, caminho_tabelas)
    inss = q2(t.salario_minimo * aliquota)
    return {
        "status": "success",
        "atividade": nome,
        "salario_minimo": float(q2(t.salario_minimo)),
        "inss": float(inss),
        "icms": float(icms),
        "iss": float(iss),
        "valor": float(q2(inss + icms + iss)),
        "vencimento": _vencimento_no_mes_seguinte(competencia, 20).isoformat(),
        "avisos": [
            "Vencimento no dia 20 do mês seguinte (próximo dia útil se cair em fim de semana ou feriado nacional; feriados estaduais e municipais não entram no cálculo).",
            f"INSS de {aliquota * 100:.0f}% do salário mínimo, mais ICMS e/ou ISS fixos conforme a atividade (LC 123/2006, art. 18-A).",
        ],
        "tabela": f"{t.norma} [{t.verificacao}]",
        "competencia": _competencia_str(competencia),
    }


# ----------------------------------------------------------------------------------------------------------- DARF
MULTA_DIARIA = Decimal("0.0033")  # 0,33% por dia de atraso
MULTA_MAXIMA = Decimal("0.20")  # limitada a 20%
JUROS_MES_DO_PAGAMENTO = Decimal("0.01")


def calcular_darf(principal, vencimento, pagamento, selic_acumulada=None, codigo_receita: Optional[str] = None) -> Dict[str, Any]:
    """DARF pago em atraso (tributos federais, Lei 9.430/1996, art. 61 e art. 5º, § 3º).

    Multa de mora: 0,33% por dia de atraso, limitada a 20%. Juros: SELIC acumulada do mês seguinte ao do vencimento até o mês
    anterior ao do pagamento, mais 1% no mês do pagamento. A SELIC acumulada é dado externo (a Receita publica a tabela): se
    há meses cheios entre o vencimento e o pagamento e ela não foi informada, o cálculo pergunta, não estima.
    """
    valor = nao_negativo(D(principal, "valor principal"), "valor principal")
    if valor <= 0:
        raise DadosInvalidos("valor principal: informe um valor maior que zero")
    venc, pag = ler_data(vencimento, "vencimento"), ler_data(pagamento, "pagamento")
    atraso = (pag - venc).days
    avisos: List[str] = ["Use o vencimento efetivo: se o prazo caiu em dia sem expediente, ele é prorrogado para o dia útil seguinte."]
    multa = juros = ZERO
    taxa_multa = taxa_juros = ZERO
    meses_cheios = 0
    selic = None
    if atraso <= 0:
        avisos.append("Pago no prazo: sem multa nem juros.")
    else:
        taxa_multa = min(MULTA_DIARIA * atraso, MULTA_MAXIMA)
        multa = q2(valor * taxa_multa)
        diferenca_de_meses = (pag.year - venc.year) * 12 + (pag.month - venc.month)
        if diferenca_de_meses == 0:
            avisos.append("Pago no mesmo mês do vencimento: só multa de mora (juros começam no mês seguinte).")
        else:
            meses_cheios = diferenca_de_meses - 1
            if meses_cheios > 0:
                if selic_acumulada in (None, ""):
                    raise FaltamDados(
                        ["selic_acumulada"],
                        "Para calcular os juros, preciso da taxa SELIC acumulada (em %) do mês seguinte ao vencimento até o mês anterior ao pagamento "
                        "(a Receita publica a tabela).",
                    )
                selic = nao_negativo(D(selic_acumulada, "SELIC acumulada"), "SELIC acumulada")
            taxa_juros = (selic / 100 if selic is not None else ZERO) + JUROS_MES_DO_PAGAMENTO
            juros = q2(valor * taxa_juros)
    total = q2(valor + multa + juros)
    return {
        "status": "success",
        "codigo_receita": codigo_receita,
        "valor_principal": float(q2(valor)),
        "dias_de_atraso": max(atraso, 0),
        "taxa_multa": float(taxa_multa),
        "multa": float(multa),
        "meses_entre_vencimento_e_pagamento": meses_cheios,
        "selic_acumulada": None if selic is None else float(selic),
        "taxa_juros": float(taxa_juros),
        "juros": float(juros),
        "total": float(total),
        "vencimento": venc.isoformat(),
        "pagamento": pag.isoformat(),
        "avisos": avisos,
        "tabela": "Lei nº 9.430/1996, art. 61 e art. 5º, § 3º (multa de 0,33% ao dia até 20%; juros SELIC + 1% no mês do pagamento)",
    }
