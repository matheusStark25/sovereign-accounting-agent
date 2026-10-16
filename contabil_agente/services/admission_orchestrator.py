from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("admission_orchestrator")

# Guarded imports to avoid hard dependency failures during lint/type-check
try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None

try:
    # Event bus should expose a publish/subscribe interface
    from contabil_agente.services.event_bus import AsyncEventBus, get_event_bus
except Exception:
    AsyncEventBus = None
    get_event_bus = None

try:
    from contabil_agente.services.cadastral_validator import CadastralValidator
except Exception:
    CadastralValidator = None

try:
    from contabil_agente.services.legacy_sync_service import LegacySyncService
except Exception:
    LegacySyncService = None


class AdmissionOrchestrator:
    """Saga-style orchestrator for Admissão Digital.

    Responsibilities:
    - Advance admission through deterministic states
    - Persist checkpoints to DatabaseService
    - Emit events via AsyncEventBus
    - Perform compensations on permanent failures
    """

    STATES = [
        "RECEBIDO",
        "QUALIFICANDO",
        "CADASTRANDO_LEGADO",
        "ENVIANDO_ESOCIAL",
        "GERANDO_DOCS",
        "FINALIZADO",
    ]

    def __init__(
        self,
        db: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        validator: Optional[Any] = None,
        legacy: Optional[Any] = None,
        supervisor: Optional[Any] = None,
    ):
        self.db = db or (DatabaseService() if DatabaseService else None)
        self.event_bus = event_bus or (get_event_bus() if get_event_bus else None)
        self.validator = validator or (
            CadastralValidator() if CadastralValidator else None
        )
        self.legacy = legacy or (LegacySyncService() if LegacySyncService else None)
        self._running: Dict[str, asyncio.Task] = {}
        self.supervisor = supervisor

    def start_admission(self, correlation_id: str, payload: Dict[str, Any]) -> None:
        """Begin the admission saga asynchronously.

        correlation_id: unique id used across DB records and events
        payload: raw submission data (contains cnpj/cpf, documents)
        """
        # persist initial checkpoint
        try:
            if self.db:
                self.db.record_processamento(correlation_id, "RECEBIDO", str(payload))
        except Exception:
            logger.debug("failed to persist RECEBIDO for %s", correlation_id)

        if self.event_bus:
            try:
                self.event_bus.publish(
                    "admission.received",
                    {"correlation_id": correlation_id, "payload": payload},
                )
            except Exception:
                logger.debug(
                    "event publish failed for admission.received %s", correlation_id
                )

        # schedule the saga runner
        task = asyncio.create_task(self._run_saga(correlation_id, payload))
        self._running[correlation_id] = task

        # Register a restart callback with supervisor if available
        try:
            if self.supervisor and hasattr(
                self.supervisor, "register_restart_callback"
            ):
                self.supervisor.register_restart_callback(
                    correlation_id,
                    lambda wid: asyncio.create_task(self._restart_from_checkpoint(wid)),
                )
        except Exception:
            logger.debug("failed to register restart callback for %s", correlation_id)

    async def _restart_from_checkpoint(self, correlation_id: str):
        logger.info(
            "Restart requested for admission %s, resuming from DB checkpoint",
            correlation_id,
        )
        # Attempt to resume by reading last status and re-enqueueing the saga
        try:
            if not self.db:
                return
            last = self.db.get_last_processamento(correlation_id)
            if not last:
                logger.warning("No checkpoint found for %s", correlation_id)
                return
            payload = last.get("payload") or {}
            # schedule runner (fire-and-forget)
            if (
                correlation_id in self._running
                and not self._running[correlation_id].done()
            ):
                logger.info("Admission %s already running", correlation_id)
                return
            self._running[correlation_id] = asyncio.create_task(
                self._run_saga(correlation_id, payload)
            )
        except Exception:
            logger.exception("_restart_from_checkpoint failed for %s", correlation_id)

    async def _run_saga(self, correlation_id: str, payload: Dict[str, Any]):
        start_ts = time.time()
        try:
            # Step: QUALIFICANDO
            await self._set_state(correlation_id, "QUALIFICANDO", payload)
            qual = {
                "ok": True,
                "reason": None,
                "normalized": payload,
            }
            if self.validator:
                try:
                    qual = await self.validator.validate(payload)
                except Exception:
                    logger.exception("validator failed for %s", correlation_id)

            if not qual.get("ok"):
                # Irreversible: compensation flow
                await self._compensate(
                    correlation_id,
                    payload,
                    qual.get("reason") or "qualification_failed",
                )
                return

            # Step: CADASTRANDO_LEGADO
            await self._set_state(correlation_id, "CADASTRANDO_LEGADO", payload)
            try:
                if self.legacy and hasattr(self.legacy, "register_company"):
                    # attempt legacy registration (may be I/O bound)
                    await asyncio.wait_for(
                        self.legacy.register_company(payload), timeout=120
                    )
                else:
                    logger.debug(
                        "legacy register unavailable, skipping for %s", correlation_id
                    )
            except Exception:
                logger.exception("legacy registration failed for %s", correlation_id)

            # Step: ENVIANDO_ESOCIAL
            await self._set_state(correlation_id, "ENVIANDO_ESOCIAL", payload)
            try:
                # publish an event so delivery systems may pick it up
                if self.event_bus:
                    self.event_bus.publish(
                        "admission.send_esocial",
                        {"correlation_id": correlation_id, "payload": payload},
                    )
            except Exception:
                logger.debug("failed to publish esocial event for %s", correlation_id)

            # Step: GERANDO_DOCS
            await self._set_state(correlation_id, "GERANDO_DOCS", payload)
            try:
                # attempt to create documents (pdfs, receipts) and persist
                doc = {
                    "correlation_id": correlation_id,
                    "type": "receipt",
                    "content": f"Admissao for {correlation_id}",
                }
                if self.db and hasattr(self.db, "save_document"):
                    self.db.save_document(correlation_id, doc)
            except Exception:
                logger.exception("document generation failed for %s", correlation_id)

            # Step: FINALIZADO
            await self._set_state(correlation_id, "FINALIZADO", payload)
            if self.event_bus:
                try:
                    self.event_bus.publish(
                        "admission.completed",
                        {
                            "correlation_id": correlation_id,
                            "duration": time.time() - start_ts,
                        },
                    )
                except Exception:
                    logger.debug(
                        "failed to publish admission.completed %s", correlation_id
                    )

        except Exception:
            logger.exception("Admission saga failed for %s", correlation_id)
            await self._compensate(correlation_id, payload, "unexpected_error")

    async def _set_state(
        self, correlation_id: str, state: str, payload: Dict[str, Any]
    ):
        try:
            if self.db:
                self.db.record_processamento(correlation_id, state, str(payload))
        except Exception:
            logger.debug("failed to persist state %s for %s", state, correlation_id)
        if self.event_bus:
            try:
                self.event_bus.publish(
                    f"admission.state.{state.lower()}",
                    {"correlation_id": correlation_id, "state": state},
                )
            except Exception:
                logger.debug(
                    "event publish failed for state %s %s", state, correlation_id
                )

    async def _compensate(
        self, correlation_id: str, payload: Dict[str, Any], reason: str
    ):
        logger.warning("Compensating admission %s: %s", correlation_id, reason)
        try:
            if self.db:
                self.db.record_processamento(correlation_id, "INCONSISTENTE", reason)
        except Exception:
            logger.debug("failed to persist compensation for %s", correlation_id)
        if self.event_bus:
            try:
                self.event_bus.publish(
                    "admission.compensation_required",
                    {"correlation_id": correlation_id, "reason": reason},
                )
            except Exception:
                logger.debug(
                    "failed to publish compensation event for %s", correlation_id
                )


__all__ = ["AdmissionOrchestrator"]
