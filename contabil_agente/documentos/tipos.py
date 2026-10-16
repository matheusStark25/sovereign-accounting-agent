"""Registro dos tipos de documento: como reconhecer, o que extrair e o que conferir.

Cada ``TipoDocumento`` traz assinaturas (expressões com peso) para a classificação, uma função de extração
e uma de conferência. A conferência usa o motor ``contabil_agente.calc`` (INSS, IRRF e FGTS recalculados) e
regras aritméticas e de estrutura (somas, dígitos verificadores, contagem de registros do SPED).
Nada é inventado: campo que não foi encontrado fica fora de ``dados`` e entra em ``faltando``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from contabil_agente.calc import CalculoError, calcular_fgts_mensal, calcular_inss, calcular_irrf_mensal
from contabil_agente.calc.tables import tabela_inss

from . import extratores as ex
from .leitura import Conteudo
from .validadores import formatar_cnpj, validar_chave_acesso, validar_cnpj, validar_cpf, validar_pis

CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Alerta:
    codigo: str
    mensagem: str
    severidade: str = "aviso"  # info | aviso | erro

    def to_dict(self) -> Dict[str, str]:
        return {"codigo": self.codigo, "mensagem": self.mensagem, "severidade": self.severidade}


Extrator = Callable[[Conteudo], Dict[str, Any]]
Conferencia = Callable[[Dict[str, Any], Conteudo], Tuple[List[Alerta], Dict[str, Any]]]


@dataclass(frozen=True)
class TipoDocumento:
    codigo: str
    nome: str
    categoria: str
    assinaturas: Tuple[Tuple[str, int], ...]
    esperados: Tuple[str, ...]
    extrair: Extrator
    conferir: Optional[Conferencia] = None
    observacao: str = ""

    @property
    def peso_maximo(self) -> int:
        return sum(p for _, p in self.assinaturas)


def corpus(c: Conteudo) -> str:
    if c.xml is not None:
        nomes = " ".join(sorted({ex.local(el.tag) for el in c.xml.iter()}))
        return f"{nomes}\n{c.texto}"
    return c.texto


def _fmt(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else f"{valor:.2f}"


def _mantem(dados: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in dados.items() if v not in (None, "", [])}


def _diferenca(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b).quantize(CENTAVO)


# ------------------------------------------------------------------ extratores comuns
def _comum(rotulos_valor: Dict[str, Tuple[str, ...]]) -> Extrator:
    def extrair(c: Conteudo) -> Dict[str, Any]:
        t = c.texto
        dados: Dict[str, Any] = {
            "competencia": ex.competencia(t),
            "cnpj": ex.primeiro(ex.cnpjs_validos(t)),
            "cpf": ex.primeiro(ex.cpfs_validos(t)),
        }
        for campo, rotulos in rotulos_valor.items():
            dados[campo] = _fmt(ex.valor_apos(t, *rotulos))
        return _mantem(dados)

    return extrair


# --------------------------------------------------------------------------- holerite
_HOLERITE = {
    "salario_base": (r"sal[aá]rio\s*base", r"sal[aá]rio\b", r"vencimento"),
    "total_proventos": (r"total\s+de\s+proventos", r"total\s+proventos", r"total\s+vencimentos", r"proventos\b"),
    "total_descontos": (r"total\s+de\s+descontos", r"total\s+descontos", r"descontos\b"),
    "inss": (r"\bINSS\b", r"previd[eê]ncia"),
    "irrf": (r"\bIRRF\b", r"imposto\s+de\s+renda", r"(?-i:\bIR\b)"),
    "fgts": (r"\bFGTS\b",),
    "liquido": (r"l[ií]quido\s+a\s+receber", r"valor\s+l[ií]quido", r"l[ií]quido\b"),
}


def _conferir_holerite(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    calculos: Dict[str, Any] = {}
    prov = Decimal(d["total_proventos"]) if "total_proventos" in d else None
    desc = Decimal(d["total_descontos"]) if "total_descontos" in d else None
    liq = Decimal(d["liquido"]) if "liquido" in d else None
    if prov is not None and desc is not None and liq is not None:
        esperado = (prov - desc).quantize(CENTAVO)
        calculos["liquido_recalculado"] = _fmt(esperado)
        if _diferenca(esperado, liq) > CENTAVO:
            alertas.append(Alerta("liquido_nao_fecha", f"Proventos − descontos = {esperado}, mas o líquido do documento é {liq}.", "erro"))
    comp = d.get("competencia")
    if prov is None or comp is None:
        alertas.append(Alerta("sem_base_para_conferir", "Sem total de proventos ou competência: INSS e IRRF não foram recalculados.", "info"))
        return alertas, calculos
    data = date.fromisoformat(comp + "-01")
    try:
        inss = calcular_inss(prov, data)
        calculos["inss_recalculado"] = _fmt(inss.valor)
        calculos["tabela_inss"] = f"{inss.norma} [{inss.verificacao}]"
        if "inss" in d and _diferenca(inss.valor, Decimal(d["inss"])) > CENTAVO:
            alertas.append(Alerta("inss_diverge", f"INSS do documento {d['inss']}, recalculado {inss.valor} sobre {prov}.", "aviso"))
        irrf = calcular_irrf_mensal(prov, data, inss=Decimal(d["inss"]) if "inss" in d else inss.valor)
        calculos["irrf_recalculado_sem_dependentes"] = _fmt(irrf.valor)
        if "irrf" in d and _diferenca(irrf.valor, Decimal(d["irrf"])) > CENTAVO:
            alertas.append(Alerta(
                "irrf_diverge",
                f"IRRF do documento {d['irrf']}, recalculado {irrf.valor} sem dependentes; dependentes, pensão ou outras deduções podem explicar.",
                "aviso",
            ))
        fgts = calcular_fgts_mensal(prov)
        calculos["fgts_recalculado"] = _fmt(fgts.valor)
        if "fgts" in d and _diferenca(fgts.valor, Decimal(d["fgts"])) > CENTAVO:
            alertas.append(Alerta("fgts_diverge", f"FGTS do documento {d['fgts']}, 8% de {prov} = {fgts.valor}.", "aviso"))
    except CalculoError as exc:
        alertas.append(Alerta("sem_tabela", str(exc), "info"))
    return alertas, calculos


# ------------------------------------------------------------------------------ TRCT
_TRCT = {
    "saldo_salario": (r"saldo\s+de\s+sal[aá]rio",),
    "aviso_previo": (r"aviso\s+pr[eé]vio",),
    "decimo_terceiro": (r"13[ºo°]?\s*sal[aá]rio", r"d[eé]cimo\s+terceiro"),
    "ferias_proporcionais": (r"f[eé]rias\s+proporcionais",),
    "ferias_vencidas": (r"f[eé]rias\s+vencidas",),
    "multa_fgts": (r"multa\s+(?:de\s+)?(?:40|20)\s*%?\s*(?:do\s+)?FGTS", r"multa\s+rescis[oó]ria", r"multa.{0,10}FGTS"),
    "total_bruto": (r"total\s+(?:bruto|das\s+verbas|de\s+proventos)", r"valor\s+bruto"),
    "total_descontos": (r"total\s+(?:dos\s+|de\s+)?descontos",),
    "liquido": (r"valor\s+l[ií]quido", r"l[ií]quido\s+a\s+receber", r"l[ií]quido\b"),
}


def _extrair_trct(c: Conteudo) -> Dict[str, Any]:
    d = _comum(_TRCT)(c)
    d.pop("competencia", None)
    t = c.texto
    d["data_admissao"] = ex.data_apos(t, r"admiss[aã]o")
    d["data_demissao"] = ex.data_apos(t, r"(?:demiss[aã]o|afastamento|desligamento)")
    return _mantem(d)


def _conferir_trct(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    calculos: Dict[str, Any] = {}
    partes = [Decimal(d[k]) for k in ("saldo_salario", "aviso_previo", "decimo_terceiro", "ferias_proporcionais", "ferias_vencidas", "multa_fgts") if k in d]
    if "total_bruto" in d and len(partes) >= 2:
        soma = sum(partes, Decimal("0"))
        calculos["soma_das_verbas_lidas"] = _fmt(soma)
        if soma > Decimal(d["total_bruto"]) + CENTAVO:
            alertas.append(Alerta("verbas_excedem_total", f"As verbas lidas somam {soma}, acima do total bruto {d['total_bruto']}.", "aviso"))
    if all(k in d for k in ("total_bruto", "total_descontos", "liquido")):
        esperado = (Decimal(d["total_bruto"]) - Decimal(d["total_descontos"])).quantize(CENTAVO)
        calculos["liquido_recalculado"] = _fmt(esperado)
        if _diferenca(esperado, Decimal(d["liquido"])) > CENTAVO:
            alertas.append(Alerta("liquido_nao_fecha", f"Bruto − descontos = {esperado}, mas o líquido é {d['liquido']}.", "erro"))
    if "data_admissao" in d and "data_demissao" in d and d["data_demissao"] < d["data_admissao"]:
        alertas.append(Alerta("datas_invertidas", "A data de demissão é anterior à de admissão.", "erro"))
    alertas.append(Alerta("recalculo_completo", "Para recalcular a rescisão inteira, informe tipo, aviso e saldo do FGTS ao motor de cálculo.", "info"))
    return alertas, calculos


# ------------------------------------------------------------------------- guias (DARF/GPS/DAS)
def _conferir_soma(campo_total: str, componentes: Tuple[str, ...], nome: str) -> Conferencia:
    def conferir(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
        alertas: List[Alerta] = []
        calculos: Dict[str, Any] = {}
        if campo_total in d and any(k in d for k in componentes):
            soma = sum((Decimal(d[k]) for k in componentes if k in d), Decimal("0")).quantize(CENTAVO)
            calculos["total_recalculado"] = _fmt(soma)
            if _diferenca(soma, Decimal(d[campo_total])) > CENTAVO:
                alertas.append(Alerta("total_nao_fecha", f"{nome}: componentes somam {soma}, mas o total é {d[campo_total]}.", "erro"))
        return alertas, calculos

    return conferir


def _extrair_darf(c: Conteudo) -> Dict[str, Any]:
    d = _comum({
        "valor_principal": (r"valor\s+do\s+principal", r"valor\s+principal"),
        "multa": (r"valor\s+da\s+multa", r"\bmulta\b"),
        "juros": (r"juros", r"encargos"),
        "total": (r"valor\s+total", r"total\s+a\s+pagar", r"\btotal\b"),
    })(c)
    t = c.texto
    m = re.search(r"c[oó]digo\s+(?:da\s+)?receita\D{0,15}(\d{4})", t, re.IGNORECASE)
    d["codigo_receita"] = m.group(1) if m else None
    d["vencimento"] = ex.data_apos(t, r"vencimento", r"data\s+de\s+vencimento")
    return _mantem(d)


def _extrair_gps(c: Conteudo) -> Dict[str, Any]:
    d = _comum({
        "valor_inss": (r"valor\s+do\s+INSS", r"valor\s+INSS"),
        "outras_entidades": (r"valor\s+de\s+outras\s+entidades", r"outras\s+entidades"),
        "atm_multa_juros": (r"ATM", r"multa\s+e\s+juros", r"juros"),
        "total": (r"total\b", r"valor\s+total", r"valor\s+arrecadado"),
    })(c)
    m = re.search(r"c[oó]digo\s+de\s+pagamento\D{0,10}(\d{4})", c.texto, re.IGNORECASE)
    d["codigo_pagamento"] = m.group(1) if m else None
    return _mantem(d)


def _extrair_das(c: Conteudo) -> Dict[str, Any]:
    d = _comum({"valor": (r"valor\s+total\s+do\s+documento", r"valor\s+total", r"valor\s+do\s+documento")})(c)
    d["vencimento"] = ex.data_apos(c.texto, r"vencimento", r"data\s+de\s+vencimento")
    return _mantem(d)


# -------------------------------------------------------------------------- FGTS e afins
def _extrair_fgts_extrato(c: Conteudo) -> Dict[str, Any]:
    d = _comum({"saldo": (r"saldo\s+(?:total|atual|dispon[ií]vel)?", r"saldo")})(c)
    m = re.search(r"(?:PIS|NIS|PASEP|NIT)\D{0,12}(\d{3}\.?\d{5}\.?\d{2}-?\d)", c.texto, re.IGNORECASE)
    if m:
        d["pis"] = re.sub(r"\D", "", m.group(1))
    d.pop("competencia", None)
    return _mantem(d)


def _conferir_pis(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    if "pis" in d and not validar_pis(d["pis"]):
        return [Alerta("pis_invalido", "O PIS/NIS lido não passa na validação do dígito verificador.", "aviso")], {}
    return [], {}


def _extrair_fgts_guia(c: Conteudo) -> Dict[str, Any]:
    return _comum({"valor_fgts": (r"valor\s+(?:a\s+recolher|total|do\s+fgts)", r"total\s+a\s+recolher"), "base": (r"remunera[cç][aã]o\s+(?:base|total)", r"base\s+de\s+c[aá]lculo")})(c)


def _conferir_fgts_guia(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    if "base" in d and "valor_fgts" in d:
        esperado = calcular_fgts_mensal(Decimal(d["base"])).valor
        calc = {"fgts_8_por_cento": _fmt(esperado)}
        if _diferenca(esperado, Decimal(d["valor_fgts"])) > CENTAVO:
            return [Alerta("fgts_diverge", f"8% de {d['base']} = {esperado}, mas a guia traz {d['valor_fgts']} (aprendiz, doméstico ou ajustes explicam diferenças).", "aviso")], calc
        return [], calc
    return [], {}


# ----------------------------------------------------------------------------- obrigações
def _ano_calendario(t: str) -> Optional[str]:
    m = re.search(r"ano[\s-]*calend[aá]rio\D{0,10}(20\d{2})", t, re.IGNORECASE)
    return m.group(1) if m else None


def _extrair_obrigacao(c: Conteudo) -> Dict[str, Any]:
    t = c.texto
    return _mantem({
        "cnpj": ex.primeiro(ex.cnpjs_validos(t)),
        "competencia": ex.competencia(t),
        "ano_calendario": _ano_calendario(t),
        "recibo": (re.search(r"(?:n[uú]mero\s+do\s+)?recibo\D{0,12}([\d.\-]{8,})", t, re.IGNORECASE) or [None, None])[1],
    })


def _extrair_informe(c: Conteudo) -> Dict[str, Any]:
    t = c.texto
    return _mantem({
        "ano_calendario": _ano_calendario(t),
        "cnpj_fonte_pagadora": ex.primeiro(ex.cnpjs_validos(t)),
        "cpf_beneficiario": ex.primeiro(ex.cpfs_validos(t)),
        "rendimentos_tributaveis": _fmt(ex.valor_apos(t, r"total\s+dos\s+rendimentos", r"rendimentos\s+tribut[aá]veis")),
        "contribuicao_previdenciaria": _fmt(ex.valor_apos(t, r"contribui[cç][aã]o\s+previdenci[aá]ria\s+oficial", r"previd[eê]ncia\s+oficial")),
        "irrf": _fmt(ex.valor_apos(t, r"imposto\s+(?:sobre\s+a\s+renda\s+)?retido\s+na\s+fonte", r"\bIRRF\b")),
        "decimo_terceiro": _fmt(ex.valor_apos(t, r"13[ºo°]?\s*sal[aá]rio", r"d[eé]cimo\s+terceiro")),
    })


def _conferir_informe(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    if "irrf" in d and "rendimentos_tributaveis" in d and Decimal(d["irrf"]) > Decimal(d["rendimentos_tributaveis"]):
        alertas.append(Alerta("irrf_maior_que_rendimento", "O imposto retido é maior que os rendimentos tributáveis.", "erro"))
    if "cpf_beneficiario" in d and not validar_cpf(d["cpf_beneficiario"]):
        alertas.append(Alerta("cpf_invalido", "CPF do beneficiário inválido.", "erro"))
    return alertas, {}


def _conferir_dirf(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    ano = d.get("ano_calendario")
    aviso = "A DIRF foi extinta: a última (ano-calendário 2024) foi entregue em 2025; desde então a informação vai pelo eSocial e pela EFD-Reinf."
    if ano and int(ano) >= 2025:
        return [Alerta("dirf_extinta", f"DIRF de ano-calendário {ano}: {aviso}", "aviso")], {}
    return [Alerta("dirf_extinta", aviso, "info")], {}


# ---------------------------------------------------------------------------------- SPED
def _sped(c: Conteudo) -> List[List[str]]:
    return ex.registros_sped(c.texto)


def _campos_0000(reg: List[str], layout: Dict[str, int]) -> Dict[str, Any]:
    def pega(nome: str) -> Optional[str]:
        i = layout.get(nome)
        return reg[i] if i is not None and i < len(reg) and reg[i] != "" else None

    dt_ini, dt_fin = pega("dt_ini"), pega("dt_fin")
    return _mantem({
        "dt_ini": ex.sped_para_iso(dt_ini) if dt_ini else None,
        "dt_fin": ex.sped_para_iso(dt_fin) if dt_fin else None,
        "nome": pega("nome"),
        "cnpj": (formatar_cnpj(pega("cnpj")) or pega("cnpj")) if pega("cnpj") else None,
        "uf": pega("uf"),
    })


LAYOUT_SPED = {
    "EFD_ICMS_IPI": {"dt_ini": 3, "dt_fin": 4, "nome": 5, "cnpj": 6, "uf": 8},
    "EFD_CONTRIBUICOES": {"dt_ini": 5, "dt_fin": 6, "nome": 7, "cnpj": 8, "uf": 9},
    "ECD": {"dt_ini": 2, "dt_fin": 3, "nome": 4, "cnpj": 5, "uf": 6},
    "ECF": {"cnpj": 3, "nome": 4, "dt_ini": 9, "dt_fin": 10},
}


def _extrator_sped(codigo: str) -> Extrator:
    def extrair(c: Conteudo) -> Dict[str, Any]:
        regs = _sped(c)
        abertura = next((r for r in regs if r[0] == "0000"), None)
        if abertura is None:
            return {}
        dados = _campos_0000(abertura, LAYOUT_SPED[codigo])
        dados["total_registros"] = len(regs)
        dados["blocos"] = sorted({r[0][0] for r in regs if r[0] and r[0][0].isalnum()})
        return dados

    return extrair


def _conferir_sped(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    regs = _sped(c)
    alertas = [Alerta("estrutura_sped", p, "erro") for p in ex.conferir_sped(regs)]
    if "cnpj" in d and not validar_cnpj(d["cnpj"]):
        alertas.append(Alerta("cnpj_invalido", "CNPJ do registro 0000 inválido.", "erro"))
    if "dt_ini" in d and "dt_fin" in d and d["dt_fin"] < d["dt_ini"]:
        alertas.append(Alerta("periodo_invertido", "A data final é anterior à inicial no registro 0000.", "erro"))
    return alertas, {"linhas_conferidas": len(regs)}


# ------------------------------------------------------------------------------------ XML
EVENTOS_ESOCIAL = {
    "evtInfoEmpregador": "S-1000", "evtTabEstab": "S-1005", "evtTabRubrica": "S-1010", "evtRemun": "S-1200",
    "evtRmnRPPS": "S-1202", "evtPgtos": "S-1210", "evtFechaEvPer": "S-1299", "evtReabreEvPer": "S-1298",
    "evtAdmissao": "S-2200", "evtAltCadastral": "S-2205", "evtAltContratual": "S-2206", "evtCAT": "S-2210",
    "evtMonit": "S-2220", "evtAfastTemp": "S-2230", "evtExpRisco": "S-2240", "evtDeslig": "S-2299",
    "evtTSVInicio": "S-2300", "evtExclusao": "S-3000",
}


def _evento(raiz) -> Optional[str]:
    for el in raiz.iter():
        nome = ex.local(el.tag)
        if nome.startswith("evt"):
            return nome
    return None


def _extrair_esocial(c: Conteudo) -> Dict[str, Any]:
    raiz = c.xml
    if raiz is None:
        return {}
    evt = _evento(raiz)
    rubricas = ex.valores_com_prefixo(raiz, "vrRubr")
    return _mantem({
        "evento": evt,
        "codigo_evento": EVENTOS_ESOCIAL.get(evt or ""),
        "periodo_apuracao": ex.texto_de(raiz, "perApur"),
        "tipo_inscricao_empregador": ex.texto_de(raiz, "ideEmpregador/tpInsc"),
        "inscricao_empregador": ex.texto_de(raiz, "ideEmpregador/nrInsc"),
        "cpf_trabalhador": ex.texto_de(raiz, "cpfTrab"),
        "data_desligamento": ex.texto_de(raiz, "infoDeslig/dtDeslig"),
        "motivo_desligamento": ex.texto_de(raiz, "infoDeslig/mtvDeslig"),
        "total_rubricas": _fmt(rubricas.get("vrRubr")),
    })


def _conferir_esocial(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    if d.get("cpf_trabalhador") and not validar_cpf(d["cpf_trabalhador"]):
        alertas.append(Alerta("cpf_invalido", "CPF do trabalhador inválido.", "erro"))
    if d.get("tipo_inscricao_empregador") == "1" and d.get("inscricao_empregador"):
        insc = d["inscricao_empregador"]
        if len(insc) == 14 and not validar_cnpj(insc):
            alertas.append(Alerta("cnpj_invalido", "CNPJ do empregador inválido.", "erro"))
    if not d.get("codigo_evento"):
        alertas.append(Alerta("evento_desconhecido", "Evento do eSocial não reconhecido.", "aviso"))
    return alertas, {}


def _extrair_reinf(c: Conteudo) -> Dict[str, Any]:
    raiz = c.xml
    if raiz is None:
        return {}
    valores = ex.valores_com_prefixo(raiz, "vlr")
    return _mantem({
        "evento": _evento(raiz),
        "periodo_apuracao": ex.texto_de(raiz, "perApur"),
        "inscricao_contribuinte": ex.texto_de(raiz, "ideContri/nrInsc"),
        "valores": {k: _fmt(v) for k, v in valores.items()} or None,
    })


def _extrair_nfe(c: Conteudo) -> Dict[str, Any]:
    raiz = c.xml
    if raiz is None:
        return {}
    inf = ex.achar(raiz, "infNFe")
    chave = (inf.get("Id") or "")[3:] if inf is not None else None
    return _mantem({
        "chave_acesso": chave,
        "numero": ex.texto_de(raiz, "ide/nNF"),
        "serie": ex.texto_de(raiz, "ide/serie"),
        "emissao": ex.texto_de(raiz, "ide/dhEmi") or ex.texto_de(raiz, "ide/dEmi"),
        "emitente_cnpj": ex.texto_de(raiz, "emit/CNPJ"),
        "emitente_nome": ex.texto_de(raiz, "emit/xNome"),
        "destinatario_documento": ex.texto_de(raiz, "dest/CNPJ") or ex.texto_de(raiz, "dest/CPF"),
        "valor_produtos": _fmt(ex.decimal_xml(raiz, "ICMSTot/vProd")),
        "valor_desconto": _fmt(ex.decimal_xml(raiz, "ICMSTot/vDesc")),
        "valor_nota": _fmt(ex.decimal_xml(raiz, "ICMSTot/vNF")),
    })


def _conferir_nfe(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    calculos: Dict[str, Any] = {}
    chave = d.get("chave_acesso")
    if chave and not validar_chave_acesso(chave):
        alertas.append(Alerta("chave_invalida", "A chave de acesso não passa na validação do dígito verificador.", "erro"))
    if chave and len(chave) == 44:
        if d.get("emitente_cnpj") and chave[6:20] != d["emitente_cnpj"]:
            alertas.append(Alerta("chave_cnpj_diverge", "O CNPJ dentro da chave de acesso não é o do emitente.", "erro"))
        if d.get("numero") and chave[25:34].lstrip("0") != d["numero"].lstrip("0"):
            alertas.append(Alerta("chave_numero_diverge", "O número da nota dentro da chave não confere com o campo nNF.", "erro"))
    if d.get("emitente_cnpj") and not validar_cnpj(d["emitente_cnpj"]):
        alertas.append(Alerta("cnpj_invalido", "CNPJ do emitente inválido.", "erro"))
    raiz = c.xml
    if raiz is not None and "valor_nota" in d:
        pega = lambda caminho: ex.decimal_xml(raiz, caminho) or Decimal("0")  # noqa: E731
        esperado = (
            pega("ICMSTot/vProd") - pega("ICMSTot/vDesc") - pega("ICMSTot/vICMSDeson") + pega("ICMSTot/vST")
            + pega("ICMSTot/vFCPST") + pega("ICMSTot/vFrete") + pega("ICMSTot/vSeg") + pega("ICMSTot/vOutro")
            + pega("ICMSTot/vII") + pega("ICMSTot/vIPI") + pega("ICMSTot/vIPIDevol")
        ).quantize(CENTAVO)
        calculos["valor_nota_recalculado"] = _fmt(esperado)
        if _diferenca(esperado, Decimal(d["valor_nota"])) > CENTAVO:
            alertas.append(Alerta("vnf_nao_fecha", f"vNF {d['valor_nota']} difere da soma dos totais ({esperado}).", "erro"))
    return alertas, calculos


# ------------------------------------------------------------------------ outros documentos
def _extrair_nfse(c: Conteudo) -> Dict[str, Any]:
    t = c.texto
    cnpjs = ex.cnpjs_validos(t)
    return _mantem({
        "cnpj_prestador": cnpjs[0] if cnpjs else None,
        "cnpj_tomador": cnpjs[1] if len(cnpjs) > 1 else None,
        "valor_servicos": _fmt(ex.valor_apos(t, r"valor\s+(?:total\s+)?dos?\s+servi[cç]os", r"valor\s+do\s+servi[cç]o")),
        "iss": _fmt(ex.valor_apos(t, r"valor\s+do\s+ISS", r"\bISS\b")),
        "competencia": ex.competencia(t),
    })


def _extrair_ferias(c: Conteudo) -> Dict[str, Any]:
    d = _comum({
        "valor_ferias": (r"valor\s+das\s+f[eé]rias", r"f[eé]rias\b"),
        "terco": (r"1/3", r"ter[cç]o\s+constitucional"),
        "abono": (r"abono\s+pecuni[aá]rio",),
        "total_bruto": (r"total\s+bruto", r"total\s+de\s+proventos"),
        "inss": (r"\bINSS\b",), "irrf": (r"\bIRRF\b",),
        "liquido": (r"l[ií]quido\s+a\s+receber", r"valor\s+l[ií]quido", r"l[ií]quido\b"),
    })(c)
    d["inicio_gozo"] = ex.data_apos(c.texto, r"in[ií]cio\s+(?:do\s+)?gozo", r"gozo\s+de", r"in[ií]cio")
    return _mantem(d)


def _extrair_contrato(c: Conteudo) -> Dict[str, Any]:
    t = c.texto
    return _mantem({
        "cnpj_empregador": ex.primeiro(ex.cnpjs_validos(t)),
        "cpf_empregado": ex.primeiro(ex.cpfs_validos(t)),
        "salario": _fmt(ex.valor_apos(t, r"sal[aá]rio\s+(?:mensal\s+)?de", r"remunera[cç][aã]o\s+(?:mensal\s+)?de", r"sal[aá]rio")),
        "data_admissao": ex.data_apos(t, r"admiss[aã]o", r"in[ií]cio\s+(?:do\s+contrato|das\s+atividades)"),
        "jornada": (re.search(r"(\d{2})\s*(?:\(.*?\)\s*)?horas\s+semanais", t, re.IGNORECASE) or [None, None])[1],
    })


def _conferir_contrato(d: Dict[str, Any], c: Conteudo) -> Tuple[List[Alerta], Dict[str, Any]]:
    alertas: List[Alerta] = []
    if "salario" in d and "data_admissao" in d:
        try:
            sm = tabela_inss(date.fromisoformat(d["data_admissao"][:7] + "-01")).salario_minimo
            if Decimal(d["salario"]) < sm:
                alertas.append(Alerta("abaixo_do_minimo", f"Salário {d['salario']} abaixo do mínimo nacional ({sm}) na admissão (confira piso da categoria).", "erro"))
        except CalculoError:
            alertas.append(Alerta("sem_tabela", "Sem tabela para a competência da admissão: salário mínimo não conferido.", "info"))
    if "jornada" in d and int(d["jornada"]) > 44:
        alertas.append(Alerta("jornada_acima_do_limite", "Jornada semanal acima de 44 horas (CF art. 7º, XIII).", "erro"))
    return alertas, {}


def _extrair_aso(c: Conteudo) -> Dict[str, Any]:
    t = c.texto
    tipo = re.search(r"\b(admissional|demissional|peri[oó]dico|retorno ao trabalho|mudan[cç]a de risco)\b", t, re.IGNORECASE)
    apto = re.search(r"\b(inapto|apto)\b", t, re.IGNORECASE)
    return _mantem({
        "tipo_exame": tipo.group(1).lower() if tipo else None,
        "resultado": apto.group(1).lower() if apto else None,
        "data_exame": ex.data_apos(t, r"data\s+(?:do\s+)?exame", r"data"),
        "cnpj": ex.primeiro(ex.cnpjs_validos(t)),
        "cpf": ex.primeiro(ex.cpfs_validos(t)),
    })


def _t(codigo, nome, categoria, assinaturas, esperados, extrair, conferir=None, observacao=""):
    return TipoDocumento(codigo, nome, categoria, tuple(assinaturas), tuple(esperados), extrair, conferir, observacao)


TIPOS: Dict[str, TipoDocumento] = {t.codigo: t for t in [
    _t("HOLERITE", "Holerite / contracheque", "trabalhista",
       [(r"\b(holerite|contra-?cheque|recibo de pagamento de sal[aá]rio|demonstrativo de pagamento)\b", 4), (r"\bproventos\b", 2), (r"\bdescontos\b", 2), (r"\bl[ií]quido\b", 1), (r"\bINSS\b", 1), (r"\bFGTS\b", 1)],
       ("competencia", "total_proventos", "inss", "liquido"), _comum(_HOLERITE), _conferir_holerite),
    _t("TRCT", "Termo de Rescisão do Contrato de Trabalho", "trabalhista",
       [(r"termo de rescis[aã]o do contrato de trabalho|(?-i:\bTRCT\b)", 5), (r"aviso pr[eé]vio", 1), (r"f[eé]rias proporcionais", 1), (r"multa.{0,20}FGTS", 1)],
       ("data_admissao", "data_demissao", "liquido"), _extrair_trct, _conferir_trct),
    _t("RECIBO_FERIAS", "Recibo de férias", "trabalhista",
       [(r"recibo de f[eé]rias", 5), (r"per[ií]odo aquisitivo", 2), (r"abono pecuni[aá]rio", 1), (r"1/3|ter[cç]o constitucional", 1)],
       ("valor_ferias", "total_bruto", "liquido"), _extrair_ferias),
    _t("CONTRATO_TRABALHO", "Contrato de trabalho", "trabalhista",
       [(r"contrato (individual )?de trabalho", 4), (r"cl[aá]usula", 1), (r"\bempregador\b", 1), (r"\bempregado\b", 1), (r"jornada de trabalho", 1)],
       ("cnpj_empregador", "salario", "data_admissao"), _extrair_contrato, _conferir_contrato),
    _t("ASO", "Atestado de Saúde Ocupacional", "trabalhista",
       [(r"atestado de sa[uú]de ocupacional|(?-i:\bASO\b)", 5), (r"\b(apto|inapto)\b", 2), (r"\b(admissional|demissional|peri[oó]dico)\b", 1)],
       ("tipo_exame", "resultado"), _extrair_aso),
    _t("DARF", "DARF", "federal",
       [(r"(?-i:\bDARF\b)|documento de arrecada[cç][aã]o de receitas federais", 5), (r"c[oó]digo da receita", 2), (r"per[ií]odo de apura[cç][aã]o", 1)],
       ("cnpj", "codigo_receita", "total"), _extrair_darf, _conferir_soma("total", ("valor_principal", "multa", "juros"), "DARF")),
    _t("GPS", "Guia da Previdência Social", "previdenciario",
       [(r"guia da previd[eê]ncia social|(?-i:\bGPS\b)", 5), (r"c[oó]digo de pagamento", 2), (r"\bATM\b|juros", 1)],
       ("cnpj", "competencia", "total"), _extrair_gps, _conferir_soma("total", ("valor_inss", "outras_entidades", "atm_multa_juros"), "GPS")),
    _t("DAS", "DAS do Simples Nacional / MEI", "federal",
       [(r"documento de arrecada[cç][aã]o do simples nacional|(?-i:\bDAS\b)", 5), (r"(?-i:PGDAS)", 3), (r"simples nacional", 2)],
       ("cnpj", "competencia", "valor"), _extrair_das),
    _t("GFIP", "GFIP / SEFIP", "previdenciario",
       [(r"(?-i:\bGFIP\b|\bSEFIP\b)|guia de recolhimento do FGTS e informa", 5), (r"compet[eê]ncia", 1)],
       ("cnpj", "competencia"), _extrair_obrigacao),
    _t("GRRF", "Guia de Recolhimento Rescisório do FGTS", "fgts",
       [(r"(?-i:\bGRRF\b)|guia de recolhimento rescis[oó]rio", 5), (r"FGTS", 1)],
       ("cnpj", "valor_fgts"), _extrair_fgts_guia, _conferir_fgts_guia),
    _t("FGTS_GUIA", "Guia do FGTS Digital", "fgts",
       [(r"FGTS Digital|guia de recolhimento do FGTS|(?-i:\bGRF\b)", 4), (r"compet[eê]ncia", 1), (r"c[oó]digo de barras", 1)],
       ("cnpj", "competencia", "valor_fgts"), _extrair_fgts_guia, _conferir_fgts_guia),
    _t("FGTS_EXTRATO", "Extrato do FGTS", "fgts",
       [(r"extrato (anal[ií]tico )?(do |de )?FGTS|extrato da conta vinculada", 5), (r"\bsaldo\b", 1), (r"\b(PIS|NIS)\b", 1)],
       ("pis", "saldo"), _extrair_fgts_extrato, _conferir_pis),
    _t("DIRF", "DIRF", "federal",
       [(r"(?-i:\bDIRF\b)|declara[cç][aã]o do imposto (sobre a renda|de renda) retido na fonte", 5), (r"ano-?calend[aá]rio", 1), (r"benefici[aá]rio", 1)],
       ("cnpj", "ano_calendario"), _extrair_obrigacao, _conferir_dirf, "Extinta: última referente ao ano-calendário 2024."),
    _t("DCTF", "DCTF", "federal",
       [(r"(?-i:\bDCTF\b)(?!\s*-?\s*[Ww]eb)|declara[cç][aã]o de d[eé]bitos e cr[eé]ditos tribut[aá]rios federais", 4)],
       ("cnpj", "competencia"), _extrair_obrigacao),
    _t("DCTFWEB", "DCTFWeb", "federal", [(r"DCTF\s*-?\s*Web", 5), (r"d[eé]bitos e cr[eé]ditos", 1)],
       ("cnpj", "competencia"), _extrair_obrigacao),
    _t("PER_DCOMP", "PER/DCOMP", "federal",
       [(r"(?-i:PER/?DCOMP)|pedido de restitui[cç][aã]o|declara[cç][aã]o de compensa[cç][aã]o", 5), (r"cr[eé]dito", 1)],
       ("cnpj",), _extrair_obrigacao),
    _t("ECD", "ECD (SPED Contábil)", "sped", [(r"(?m)^\|0000\|LECD\|", 10)],
       ("dt_ini", "dt_fin", "cnpj"), _extrator_sped("ECD"), _conferir_sped),
    _t("ECF", "ECF (SPED Fiscal da RFB)", "sped", [(r"(?m)^\|0000\|LECF\|", 10)],
       ("dt_ini", "dt_fin", "cnpj"), _extrator_sped("ECF"), _conferir_sped),
    _t("EFD_ICMS_IPI", "EFD ICMS/IPI (SPED Fiscal)", "sped",
       [(r"(?m)^\|0000\|", 2), (r"(?m)^\|E100\|", 5), (r"(?m)^\|E110\|", 3), (r"(?m)^\|C100\|", 1)],
       ("dt_ini", "dt_fin", "cnpj"), _extrator_sped("EFD_ICMS_IPI"), _conferir_sped),
    _t("EFD_CONTRIBUICOES", "EFD Contribuições (PIS/Cofins)", "sped",
       [(r"(?m)^\|0000\|", 2), (r"(?m)^\|0110\|", 6), (r"(?m)^\|M\d{3}\|", 2)],
       ("dt_ini", "dt_fin", "cnpj"), _extrator_sped("EFD_CONTRIBUICOES"), _conferir_sped),
    _t("EFD_REINF", "EFD-Reinf", "xml", [(r"\bReinf\b", 5), (r"\bevt(ServTom|ServPrest|RetPF|RetPJ|InfoContri|TotalContrib)\b", 3)],
       ("evento", "periodo_apuracao"), _extrair_reinf),
    _t("ESOCIAL_XML", "Evento do eSocial (XML)", "xml", [(r"\beSocial\b", 5), (r"\bevt[A-Z]\w+\b", 2)],
       ("codigo_evento", "inscricao_empregador"), _extrair_esocial, _conferir_esocial),
    _t("CAGED", "CAGED", "trabalhista", [(r"(?-i:\bCAGED\b)|cadastro geral de empregados e desempregados", 5), (r"admiss[oõ]es|desligamentos", 1)],
       ("cnpj", "competencia"), _extrair_obrigacao),
    _t("RAIS", "RAIS", "trabalhista", [(r"(?-i:\bRAIS\b)|rela[cç][aã]o anual de informa[cç][oõ]es sociais", 5)],
       ("cnpj", "ano_calendario"), _extrair_obrigacao),
    _t("INFORME_RENDIMENTOS", "Informe de rendimentos", "federal",
       [(r"comprovante de rendimentos pagos|informe de rendimentos", 5), (r"ano-?calend[aá]rio", 1), (r"rendimentos tribut[aá]veis", 2), (r"fonte pagadora", 1)],
       ("ano_calendario", "cnpj_fonte_pagadora", "rendimentos_tributaveis"), _extrair_informe, _conferir_informe),
    _t("NFE_XML", "NF-e (XML)", "xml", [(r"\b(NFe|nfeProc|infNFe)\b", 6), (r"\bICMSTot\b", 2)],
       ("chave_acesso", "emitente_cnpj", "valor_nota"), _extrair_nfe, _conferir_nfe),
    _t("NFSE", "NFS-e", "municipal",
       [(r"nota fiscal de servi[cç]os? eletr[oô]nica|(?-i:\bNFS-?e\b)", 5), (r"\bISS\b", 1), (r"prestador", 1), (r"tomador", 1)],
       ("cnpj_prestador", "valor_servicos"), _extrair_nfse),
]}
