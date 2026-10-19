"""Agentes do sistema: TaxAgent, ValidationAgent, ReconciliationAgent, ComplianceAgent e RPAAgent, mais o orquestrador.

Cada agente usa o que o sistema já tem (motor de cálculo, validadores e pipeline de documentos, regras de conformidade e
LGPD, robôs de portal) e responde sempre com ``status`` ``ok``, ``faltam_dados`` ou ``erro``. A API expõe tudo em
``/api/v1/agentes`` (veja ``agente_v2/rotas_agentes.py``).
"""

from .base import AcaoDesconhecida, Agente, AgenteErro
from .conciliacao import ReconciliationAgent
from .conformidade import ComplianceAgent
from .orquestrador import OrquestradorDeAgentes
from .rpa import RPAAgent
from .tributario import TaxAgent
from .validacao import ValidationAgent

__all__ = [
    "AcaoDesconhecida", "Agente", "AgenteErro", "ComplianceAgent", "OrquestradorDeAgentes", "RPAAgent",
    "ReconciliationAgent", "TaxAgent", "ValidationAgent",
]
