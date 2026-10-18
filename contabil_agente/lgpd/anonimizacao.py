"""Anonimização de dados pessoais em textos, logs e saídas: CPF, CNPJ, e-mail, telefone, cartão, RG e nome."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Iterable, Mapping, Optional

_PALAVRA = r"[A-ZÀ-Ý][A-Za-zÀ-ÿ'’]+"
_LIGACAO = r"(?:(?:de|da|do|das|dos|e|DE|DA|DO|DAS|DOS|E)\s+)?"
_ROTULOS_NOME = r"nome(?:\s+completo)?|funcion[aá]rio|empregado|colaborador|benefici[aá]rio|titular|trabalhador|cliente|segurado|s[oó]cio|sr\.?|sra\.?|dr\.?|dra\.?"
# o rótulo casa sem diferenciar maiúsculas; o nome em si precisa começar com maiúscula
_RE_NOME = re.compile(rf"(?i:\b(?:{_ROTULOS_NOME})(?![A-Za-zÀ-ÿ]))(\s*[:\-]?\s*)({_PALAVRA}(?:\s+{_LIGACAO}{_PALAVRA}){{1,5}})")


# Identificadores técnicos (UUID de pedido, hash SHA-256/SHA-1 em hexadecimal) não são dado pessoal. Sem protegê-los, os
# padrões de telefone e RG casam com os 8 primeiros dígitos de um UUID e estragam a rastreabilidade (request_id, job, trilha).
_ID_TECNICO = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{40,128}\b")


class PIIAnonymizer:
    """Troca dados pessoais por marcadores (``***CPF***``) ou ``***``."""

    PATTERNS = {
        "cpf": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
        "cnpj": r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "telefone": r"\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}-?\d{4}\b",
        "rg": r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dXx]\b",
        "cartao": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
    }
    _ORDEM = ("cartao", "cnpj", "cpf", "email", "telefone", "rg")  # específico antes do genérico

    @staticmethod
    def anonymize_text(text: str, preserve_type: bool = True, nomes_conhecidos: Iterable[str] = ()) -> str:
        """Mascara PII. ``nomes_conhecidos`` (ex.: nome do titular já identificado) são trocados onde aparecerem."""
        if not text:
            return text
        marcador = (lambda t: f"***{t.upper()}***") if preserve_type else (lambda t: "***")
        guardados: list = []

        def guardar(m: "re.Match[str]") -> str:
            guardados.append(m.group(0))
            return f"@@ID{len(guardados) - 1}@@"

        resultado = _ID_TECNICO.sub(guardar, text)
        for tipo in PIIAnonymizer._ORDEM:
            resultado = re.sub(PIIAnonymizer.PATTERNS[tipo], marcador(tipo), resultado)
        resultado = _RE_NOME.sub(lambda m: f"{m.group(0)[: m.start(1) - m.start(0)]}{m.group(1)}{marcador('nome')}", resultado)
        for nome in sorted({n.strip() for n in nomes_conhecidos if n and len(n.strip()) >= 3}, key=len, reverse=True):
            resultado = re.sub(re.escape(nome), marcador("nome"), resultado, flags=re.IGNORECASE)
        for i, original in enumerate(guardados):
            resultado = resultado.replace(f"@@ID{i}@@", original)
        return resultado

    @staticmethod
    def anonymize_value(valor: object, **kw) -> object:
        """Aplica ``anonymize_text`` em textos, dicionários e listas aninhados."""
        if isinstance(valor, str):
            return PIIAnonymizer.anonymize_text(valor, **kw)
        if isinstance(valor, Mapping):
            return {k: PIIAnonymizer.anonymize_value(v, **kw) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [PIIAnonymizer.anonymize_value(v, **kw) for v in valor]
        return valor

    @staticmethod
    def hash_pii(valor: str, chave: Optional[str] = None) -> str:
        """Hash irreversível e estável (HMAC-SHA256) para usar PII como chave de busca sem guardá-la.
        A chave vem do argumento ou de ``PII_HASH_KEY``; sem chave levanta erro (nada de sal fixo no código)."""
        segredo = chave or os.environ.get("PII_HASH_KEY")
        if not segredo or len(segredo) < 16:
            raise ValueError("Defina PII_HASH_KEY (mínimo 16 caracteres) para gerar hashes de dados pessoais.")
        digitos = re.sub(r"\D", "", valor)
        base = digitos if len(digitos) in (11, 14) else valor.strip().lower()
        return hmac.new(segredo.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def mask_partial(valor: str, visible_start: int = 3, visible_end: int = 2) -> str:
        """123***45: mantém só o começo e o fim."""
        if len(valor) <= visible_start + visible_end:
            return "*" * len(valor)
        fim = valor[-visible_end:] if visible_end > 0 else ""
        return f"{valor[:visible_start]}{'*' * (len(valor) - visible_start - visible_end)}{fim}"
