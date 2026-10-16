"""Geração e processamento de documentos (PDF dos cálculos e despachante de tipos de documento)."""

from .pdf import TITULOS, gerar_pdf_calculo, hash_do_resultado

__all__ = ["TITULOS", "gerar_pdf_calculo", "hash_do_resultado"]
