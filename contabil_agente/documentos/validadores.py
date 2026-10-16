"""Validadores de documentos brasileiros (com dígitos verificadores) e formatadores."""

from __future__ import annotations

import re
from typing import Optional


def so_digitos(valor: object) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def validar_cpf(valor: object) -> bool:
    cpf = so_digitos(valor)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def validar_cnpj(valor: object) -> bool:
    cnpj = so_digitos(valor)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(tamanho))
        digito = 0 if soma % 11 < 2 else 11 - soma % 11
        if digito != int(cnpj[tamanho]):
            return False
    return True


def validar_pis(valor: object) -> bool:
    """PIS/PASEP/NIT (11 dígitos)."""
    pis = so_digitos(valor)
    if len(pis) != 11 or len(set(pis)) == 1:
        return False
    pesos = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    resto = sum(int(d) * p for d, p in zip(pis[:10], pesos)) % 11
    digito = 0 if resto < 2 else 11 - resto
    return digito == int(pis[10])


def validar_chave_acesso(valor: object) -> bool:
    """Chave de acesso de 44 dígitos (NF-e, NFC-e, CT-e): DV pelo módulo 11."""
    chave = so_digitos(valor)
    if len(chave) != 44:
        return False
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(chave[:43])))
    resto = soma % 11
    digito = 0 if resto in (0, 1) else 11 - resto
    return digito == int(chave[43])


def formatar_cpf(valor: object) -> Optional[str]:
    cpf = so_digitos(valor)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else None


def formatar_cnpj(valor: object) -> Optional[str]:
    c = so_digitos(valor)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else None


def mascarar_cpf(valor: object) -> str:
    """123.456.789-09 -> ***.456.789-** (para logs e auditoria)."""
    cpf = so_digitos(valor)
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else "***"


def mascarar_cnpj(valor: object) -> str:
    c = so_digitos(valor)
    return f"**.{c[2:5]}.{c[5:8]}/****-**" if len(c) == 14 else "***"
