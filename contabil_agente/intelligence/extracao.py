"""Extrai dados de cálculo de mensagens em português (valores, datas, tipo de rescisão...).

Determinístico e testável: serve de base quando o LLM não está disponível e como
validação das respostas do LLM. Nunca inventa um dado: o que não aparece não é devolvido.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?"
_DATA = r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(texto.lower())).strip()


def parse_valor_br(texto: str) -> Optional[Decimal]:
    """'3.000,50' -> 3000.50 ; '3000' -> 3000 ; '3.000' -> 3000 ; '3k' / '3 mil' -> 3000."""
    s = normalizar(texto).replace("r$", "").strip()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(k|mil)", s)
    if m:
        try:
            return Decimal(m.group(1).replace(",", ".")) * 1000
        except InvalidOperation:
            return None
    s = s.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _datas_no_texto(texto: str) -> List[Tuple[int, int, date]]:
    achados = []
    for m in re.finditer(_DATA, texto):
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        ano_i = int(ano) + 2000 if len(ano) == 2 else int(ano)
        try:
            achados.append((m.start(), m.end(), date(ano_i, mes, dia)))
        except ValueError:
            continue
    return achados


_CTX_ADMISSAO = re.compile(r"(admiti|admiss|contratad|contrata[cç]|entrou|comecou|iniciou|inicio)")
_CTX_DEMISSAO = re.compile(r"(demiti|demiss|desligad|desligament|dispensad|saiu|saida|rescis|mandad[oa] embora|foi embora|termino)")


def extrair_datas(mensagem: str) -> Dict[str, Any]:
    """Atribui datas a admissão/demissão pelo contexto; sem contexto, a mais antiga é a admissão."""
    norm = normalizar(mensagem)
    # as posições devem valer para o texto normalizado: normaliza e procura de novo
    datas = _datas_no_texto(norm)
    saida: Dict[str, Any] = {}
    sem_contexto: List[date] = []
    for ini, _fim, d in datas:
        janela = norm[max(0, ini - 32): ini]
        if _CTX_ADMISSAO.search(janela) and "data_admissao" not in saida:
            saida["data_admissao"] = d.isoformat()
        elif _CTX_DEMISSAO.search(janela) and "data_demissao" not in saida:
            saida["data_demissao"] = d.isoformat()
        else:
            sem_contexto.append(d)
    if sem_contexto:
        if "data_admissao" not in saida and "data_demissao" not in saida and len(sem_contexto) >= 2:
            ordenadas = sorted(sem_contexto)
            saida["data_admissao"], saida["data_demissao"] = ordenadas[0].isoformat(), ordenadas[-1].isoformat()
        else:
            saida["datas_sem_contexto"] = [d.isoformat() for d in sem_contexto]
    return saida


def extrair_tipo_rescisao(norm: str) -> Optional[str]:
    if re.search(r"\bsem justa causa\b|\bdemitid[oa] sem\b|\bdispensa sem\b", norm):
        return "sem_justa_causa"
    if re.search(r"pedido de demissao|pediu demissao|pedi demissao|pediu pra sair|pedir demissao|se demitiu", norm):
        return "pedido_demissao"
    if re.search(r"\bacordo\b|comum acordo|484", norm):
        return "acordo"
    if re.search(r"\bjusta causa\b", norm):
        return "justa_causa"
    return None


def extrair_aviso(norm: str) -> Optional[str]:
    if re.search(r"nao cumpr|nao cumpriu|sem cumprir|nao trabalhou o aviso|nao trabalhado", norm):
        return "nao_cumprido"
    if re.search(r"aviso( previo)? indenizad|indenizou o aviso|aviso pago", norm) or re.search(r"indenizad[oa]", norm):
        return "indenizado"
    if re.search(r"aviso( previo)? trabalhad|cumpriu o aviso|cumpriu aviso|trabalhou o aviso|trabalhado", norm):
        return "trabalhado"
    return None


def _valor_apos(norm: str, padrao: str) -> Optional[Decimal]:
    m = re.search(padrao + r"[^\d]{0,25}(?:r\$ ?)?(" + _NUM + r"|\d+(?:[.,]\d+)? ?(?:mil|k))", norm)
    return parse_valor_br(m.group(m.lastindex)) if m else None


def extrair_dados(mensagem: str) -> Dict[str, Any]:
    """Devolve apenas o que foi dito na mensagem. Chaves compatíveis com ``calc.servico``."""
    norm = normalizar(mensagem)
    dados: Dict[str, Any] = {}

    dados.update(extrair_datas(mensagem))

    # saldo do FGTS (antes do salário para não confundir os valores)
    texto_sem_fgts = norm
    saldo = _valor_apos(norm, r"saldo (?:do |de |no )?(?:fgts|fundo de garantia)(?: (?:de|e|eh|esta em|:))?")
    if saldo is not None:
        dados["saldo_fgts"] = saldo
        texto_sem_fgts = re.sub(r"saldo (?:do |de |no )?(?:fgts|fundo de garantia)[^\d]{0,25}(?:r\$ ?)?[\d.,]+", " ", norm)
    elif re.search(r"(sem|nao sei o|nao tenho o|nao tenho) (o )?saldo|saldo (nao sei|desconhecido)", norm):
        dados["recusou_saldo_fgts"] = True

    # remove datas para não virarem valores
    texto_valores = re.sub(_DATA, " ", texto_sem_fgts)

    salario = _valor_apos(texto_valores, r"(?:salario(?: base| bruto| mensal)?|ganha(?:va)?|recebe(?:u|ndo)?|remuneracao)(?: (?:de|e|eh|era|:))?")
    if salario is None:
        m = re.search(r"r\$ ?(" + _NUM + r")", texto_valores)
        if m:
            salario = parse_valor_br(m.group(1))
    if salario is None:
        # "INSS de 5000", "imposto de renda sobre 6.500" (sem R$ nem a palavra salário)
        m = re.search(
            r"(?:inss|irrf|imposto(?: de renda)?|previdencia|contribuicao)[^\d]{0,25}(" + _NUM + r"|\d+(?:[.,]\d+)? ?(?:mil|k))\b",
            texto_valores,
        )
        if m:
            salario = parse_valor_br(m.group(1))
    if salario is not None and salario > 0:
        dados["salario"] = salario

    tipo = extrair_tipo_rescisao(norm)
    if tipo:
        dados["tipo_rescisao"] = tipo
    aviso = extrair_aviso(norm)
    if aviso:
        dados["aviso_previo"] = aviso

    m = re.search(r"(\d{1,2}) ?dependentes?", norm)
    if m:
        dados["dependentes"] = int(m.group(1))
    elif re.search(r"sem dependentes?|nenhum dependente|nao tem dependentes?", norm):
        dados["dependentes"] = 0

    m = re.search(r"(\d{1,2}) ?(?:meses|mes)\b", norm)
    if m and 1 <= int(m.group(1)) <= 12:
        dados["meses"] = int(m.group(1))

    m = re.search(r"(?:vend(?:er|a|endo|eu)|abono)[^\d]{0,15}(\d{1,2}) ?dias?", norm)
    if m:
        dados["dias_vendidos"] = int(m.group(1))
    m = re.search(r"(\d{1,2}) ?dias? de ferias|ferias de (\d{1,2}) ?dias?", norm)
    if m:
        dados["dias_ferias"] = int(m.group(1) or m.group(2))

    m = re.search(r"(\d+) ?periodos? (?:de )?ferias vencid", norm) or re.search(r"(\d+) ?ferias vencidas", norm)
    if m:
        dados["periodos_ferias_vencidas"] = int(m.group(1))
    elif re.search(r"ferias vencidas?", norm) and not re.search(r"(sem|nao tem|nao tinha|nenhuma) ferias vencidas?", norm):
        dados["periodos_ferias_vencidas"] = 1
    elif re.search(r"(sem|nao tem|nao tinha|nenhuma) ferias vencidas?", norm):
        dados["periodos_ferias_vencidas"] = 0

    pensao = _valor_apos(norm, r"pensao(?: alimenticia)?(?: (?:de|e|:))?")
    if pensao is not None:
        dados["pensao_alimenticia"] = pensao
    adicional = _valor_apos(norm, r"(?:periculosidade|insalubridade|adicional)(?: (?:de|e|:))?")
    if adicional is not None:
        dados["adicionais_mensais"] = adicional
    return dados


def detectar_tipo_calculo(mensagem: str) -> Optional[str]:
    """Qual cálculo o usuário pediu, ou None se a mensagem não pede cálculo."""
    norm = normalizar(mensagem)
    if re.search(r"rescis|demiss|demitid|demitir|demiti\b|desligad|desligament|dispensad|mandar embora|mandei embora|acerto|verbas rescis", norm):
        return "rescisao"
    if re.search(r"13|decimo terceiro|13o", norm) and not re.search(r"\b13\d{2,}", norm):
        return "decimo_terceiro"
    if re.search(r"\bferias\b", norm):
        return "ferias"
    if re.search(r"\bfolha\b|holerite|contracheque|contra cheque|recibo de pagamento", norm):
        return "folha"
    if re.search(r"\bfgts\b", norm) and re.search(r"mensal|deposito|quanto|calcul", norm):
        return "fgts"
    if re.search(r"\birrf\b|imposto de renda|\birpf\b|\bimposto\b", norm):
        return "irrf"
    if re.search(r"\binss\b|previdencia|contribuicao previdenciaria", norm):
        return "inss"
    return None
