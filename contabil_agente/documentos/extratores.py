"""Funções de extração reutilizáveis: valores, datas, competência, CNPJ/CPF e leitores de SPED e XML."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional
from xml.etree.ElementTree import Element

from .validadores import formatar_cnpj, formatar_cpf, validar_cnpj, validar_cpf

_VALOR = r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})(?!\d)(?!\s*%)"
MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def decimal_br(texto: str) -> Optional[Decimal]:
    try:
        return Decimal(texto.replace(".", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def valor_apos(texto: str, *rotulos: str, janela: int = 70) -> Optional[Decimal]:
    """Primeiro valor monetário (formato 1.234,56) que aparece logo depois de algum dos rótulos."""
    for rotulo in rotulos:
        for achado in re.finditer(rotulo, texto, re.IGNORECASE):
            trecho = texto[achado.end(): achado.end() + janela].split("\n", 1)[0]
            m = re.search(_VALOR, trecho)
            if m:
                return decimal_br(m.group(1))
    return None


def data_para_iso(dia: int, mes: int, ano: int) -> Optional[str]:
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def data_apos(texto: str, *rotulos: str, janela: int = 40) -> Optional[str]:
    for rotulo in rotulos:
        for achado in re.finditer(rotulo, texto, re.IGNORECASE):
            trecho = texto[achado.end(): achado.end() + janela]
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", trecho)
            if m:
                iso = data_para_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if iso:
                    return iso
    return None


def competencia(texto: str, *rotulos: str) -> Optional[str]:
    """Competência 'AAAA-MM' a partir de 'MM/AAAA' ou 'mês de AAAA' depois dos rótulos (ou do texto todo)."""
    rotulos = rotulos or (r"compet[eê]ncia", r"refer[eê]ncia", r"per[ií]odo de apura[cç][aã]o", r"m[eê]s")
    for rotulo in rotulos:
        for achado in re.finditer(rotulo, texto, re.IGNORECASE):
            trecho = texto[achado.end(): achado.end() + 40]
            m = re.search(r"(\d{1,2})\s*[/-]\s*(\d{4})", trecho)
            if m and 1 <= int(m.group(1)) <= 12:
                return f"{m.group(2)}-{int(m.group(1)):02d}"
            m = re.search(r"([A-Za-zçÇ]+)\s*(?:de|/)?\s*(\d{4})", trecho)
            if m and m.group(1).lower() in MESES:
                return f"{m.group(2)}-{MESES[m.group(1).lower()]:02d}"
    return None


def cnpjs_validos(texto: str) -> List[str]:
    achados = re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto)
    vistos: List[str] = []
    for a in achados:
        f = formatar_cnpj(a)
        if f and validar_cnpj(a) and f not in vistos:
            vistos.append(f)
    return vistos


def cpfs_validos(texto: str) -> List[str]:
    achados = re.findall(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", texto)
    vistos: List[str] = []
    for a in achados:
        f = formatar_cpf(a)
        if f and validar_cpf(a) and f not in vistos:
            vistos.append(f)
    return vistos


def primeiro(lista: Iterable):
    for item in lista:
        return item
    return None


def sped_para_iso(valor: str) -> Optional[str]:
    """DDMMAAAA -> AAAA-MM-DD."""
    if len(valor) == 8 and valor.isdigit():
        return data_para_iso(int(valor[:2]), int(valor[2:4]), int(valor[4:]))
    return None


# ----------------------------------------------------------------------------- SPED
def registros_sped(texto: str) -> List[List[str]]:
    """Linhas do arquivo SPED (delimitado por |) como listas de campos, sem os pipes das pontas."""
    saida: List[List[str]] = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("|") and linha.endswith("|"):
            saida.append(linha[1:-1].split("|"))
    return saida


def conferir_sped(registros: List[List[str]]) -> List[str]:
    """Problemas de estrutura: abertura 0000, fechamento 9999 e contagem de linhas."""
    problemas: List[str] = []
    if not registros or registros[0][0] != "0000":
        problemas.append("O arquivo não começa com o registro 0000.")
    if not registros or registros[-1][0] != "9999":
        problemas.append("O arquivo não termina com o registro 9999.")
    else:
        try:
            declarado = int(registros[-1][1])
            if declarado != len(registros):
                problemas.append(f"O registro 9999 declara {declarado} linhas, mas o arquivo tem {len(registros)}.")
        except (IndexError, ValueError):
            problemas.append("Registro 9999 sem a quantidade de linhas.")
    return problemas


# ------------------------------------------------------------------------------ XML
def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def achar(raiz: Element, caminho: str) -> Optional[Element]:
    """Primeiro elemento do caminho de nomes locais (ex.: ``'emit/CNPJ'``), em qualquer profundidade."""
    partes = caminho.split("/")

    def descer(no: Element, resto: List[str]) -> Optional[Element]:
        if not resto:
            return no
        for filho in no:
            if local(filho.tag) == resto[0]:
                achado = descer(filho, resto[1:])
                if achado is not None:
                    return achado
        return None

    for el in raiz.iter():
        if local(el.tag) == partes[0]:
            achado = descer(el, partes[1:])
            if achado is not None:
                return achado
    return None


def texto_de(raiz: Element, caminho: str) -> Optional[str]:
    el = achar(raiz, caminho)
    return None if el is None or el.text is None else el.text.strip()


def decimal_xml(raiz: Element, caminho: str) -> Optional[Decimal]:
    valor = texto_de(raiz, caminho)
    if valor is None:
        return None
    try:
        return Decimal(valor)
    except InvalidOperation:
        return None


def todos(raiz: Element, nome: str) -> List[Element]:
    return [el for el in raiz.iter() if local(el.tag) == nome]


def valores_com_prefixo(raiz: Element, prefixo: str) -> Dict[str, Decimal]:
    saida: Dict[str, Decimal] = {}
    for el in raiz.iter():
        nome = local(el.tag)
        if nome.startswith(prefixo) and el.text and el.text.strip():
            try:
                saida[nome] = saida.get(nome, Decimal("0")) + Decimal(el.text.strip())
            except InvalidOperation:
                continue
    return saida
