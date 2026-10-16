"""Governança: redação de dados pessoais em logs (a trilha de auditoria está em ``security.worm_audit``)."""

from .redaction import RedactionFilter, instalar_filtro_de_redacao, sanitize_text

__all__ = ["RedactionFilter", "instalar_filtro_de_redacao", "sanitize_text"]
