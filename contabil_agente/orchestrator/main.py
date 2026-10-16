"""Ponto de entrada do orquestrador de documentos (``DocumentDispatcher``).

    from contabil_agente.orchestrator.main import DocumentDispatcher

    dispatcher = DocumentDispatcher.do_ambiente("./dados")
    resultado = dispatcher.process(document_path="dirf_2024.pdf", document_type="DIRF", persona="MARCOS")
    resultado.extracted_data, resultado.calculations, resultado.audit_trail_id
"""

from contabil_agente.pipeline.dispatcher import DocumentDispatcher

__all__ = ["DocumentDispatcher"]
