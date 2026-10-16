"""Orquestrador: coordena o pipeline de documentos (7 estados, agentes e trilha WORM)."""

from .main import DocumentDispatcher

__all__ = ["DocumentDispatcher"]
