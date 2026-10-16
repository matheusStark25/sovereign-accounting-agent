"""
Orquestrador do Sistema - Gerencia detecção de intenção e coordenação de ferramentas

Este módulo contém:
- DocumentDispatcher: Detecta 23 tipos de documentos e intenções
- UniversalDPOrchestrator: Coordena conversação e execução de tarefas

Uso:
    from contabil_agente.orchestrator import DocumentDispatcher, UniversalDPOrchestrator

    orchestrator = UniversalDPOrchestrator()
    response = orchestrator.processar_solicitacao(mensagem, session_id, usuario_cpf)
"""

from .dispatcher import DocumentDispatcher
from .main import UniversalDPOrchestrator

__all__ = [
    "DocumentDispatcher",
    "UniversalDPOrchestrator",
]
