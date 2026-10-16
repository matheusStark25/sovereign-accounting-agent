"""Redação de dados pessoais nos logs: filtro que mascara CPF, CNPJ, e-mail, telefone e nomes rotulados."""

from __future__ import annotations

import logging

from contabil_agente.lgpd.anonimizacao import PIIAnonymizer


def sanitize_text(texto: str) -> str:
    return PIIAnonymizer.anonymize_text(texto) if texto else texto


class RedactionFilter(logging.Filter):
    """Troca a mensagem já formatada por uma versão sem dados pessoais (e descarta os argumentos)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize_text(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - log nunca pode derrubar a aplicação
            record.msg = "[mensagem de log suprimida: falha na redação]"
            record.args = ()
        return True


def instalar_filtro_de_redacao(logger: logging.Logger | None = None) -> RedactionFilter:
    """Instala o filtro nos *handlers* do logger (o filtro do logger não vale para mensagens de filhos)."""
    alvo = logger or logging.getLogger()
    filtro = RedactionFilter()
    for handler in alvo.handlers:
        handler.addFilter(filtro)
    return filtro
