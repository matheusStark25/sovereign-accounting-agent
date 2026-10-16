"""Celery task scaffold for voice processing.

Provides asynchronous entrypoints for off-loop TTS/STT work.
This module works when Celery is available; otherwise it exposes
local synchronous fallbacks with the same API surface.
"""

from __future__ import annotations

from typing import Any, Dict
import logging

from contabil_agente.tools.voz_tool import ToolVoz
from contabil_agente.celery_app import celery_app, CELERY_CONFIGURED

logger = logging.getLogger(__name__)

# Initialize ToolVoz instance (best-effort)
_voc = ToolVoz()


if CELERY_CONFIGURED and celery_app is not None:

    @celery_app.task(bind=True, name="contabil_agente.voice.synthesize_audio_task")
    def synthesize_audio_task(
        self, session_id: str, text: str, filename: str | None = None
    ) -> Dict[str, Any]:
        """Celery task wrapper for TTS. Returns result dict from ToolVoz.sintetizar_voz."""
        try:
            return _voc.sintetizar_voz(
                text, salvar_arquivo=bool(filename), filename=filename
            )
        except Exception as e:
            logger.exception("synthesize_audio_task failed: %s", e)
            return {"status": "error", "message": str(e)}

    @celery_app.task(bind=True, name="contabil_agente.voice.transcribe_file_task")
    def transcribe_file_task(
        self, audio_path: str, language: str = "pt-BR"
    ) -> Dict[str, Any]:
        try:
            return _voc.transcrever_arquivo(audio_path, language=language)
        except Exception as e:
            logger.exception("transcribe_file_task failed: %s", e)
            return {"status": "error", "message": str(e)}

else:
    # synchronous fallbacks (same signatures)
    def synthesize_audio_task(
        session_id: str, text: str, filename: str | None = None
    ) -> Dict[str, Any]:
        try:
            return _voc.sintetizar_voz(
                text, salvar_arquivo=bool(filename), filename=filename
            )
        except Exception as e:
            logger.exception("synthesize_audio_task (sync) failed: %s", e)
            return {"status": "error", "message": str(e)}

    def transcribe_file_task(
        audio_path: str, language: str = "pt-BR"
    ) -> Dict[str, Any]:
        try:
            return _voc.transcrever_arquivo(audio_path, language=language)
        except Exception as e:
            logger.exception("transcribe_file_task (sync) failed: %s", e)
            return {"status": "error", "message": str(e)}
