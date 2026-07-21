"""
BaseSovereignTool

Este módulo fornece uma base abstrata e opinionada para ferramentas "Sovereign":
- Logs estruturados em JSON
- Idempotência (exactly-once) via WORM local (fácil de adaptar para DB)
- Hooks para Crypto-Anchoring, PQC e ZKP (implementações placeholder/injectable)
- Resiliência: circuit breaker simples, modo air-gapped e manual override
- Green FinOps: estimativa de carbono por operação (placeholder)
- Legal-as-Code: motor mínimo para Effective Dates

Implementações reais de DLT/PQC/ZKP devem ser fornecidas por integrações
seguras externas. Aqui oferecemos interfaces, validações e armazenamento
de auditoria imutável (WORM file append).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from core.config import Config
from utils.audit import send_audit

logger = logging.getLogger(__name__)


class BaseSovereignTool:
    """Classe base para ferramentas que fazem parte do "Sovereign Protocol".

    Observações:
    - Fornece mecanismos de auditoria, idempotência (exactly-once via WORM),
      placeholders para Crypto-Anchoring/PQC/ZKP e ferramentas de resiliência.
    - Implementações sensíveis (PQC, DLT anchoring, gov.br ZKP) devem ser
      injetadas por composição em ambiente de produção.
    """

    def __init__(self, db_pool: Optional[Any] = None, service_name: str = "tool"):
        self.db_pool = db_pool
        self.service_name = service_name
        self.session_lock = threading.Lock()
        # Use Config.BASE_DIR when available, otherwise fallback to cwd
        try:
            # Prefer Config.BASE_DIR when explicitly configured for production
            cfg_base = getattr(Config, "BASE_DIR", None)
            if cfg_base:
                base_dir = cfg_base
            else:
                # Use a dedicated sovereign data dir inside cwd to avoid accidental writes
                base_dir = os.path.join(os.getcwd(), ".sovereign_data")
        except Exception:
            base_dir = os.path.join(os.getcwd(), ".sovereign_data")

        # Ensure directory exists and set restrictive permissions where possible
        try:
            os.makedirs(base_dir, exist_ok=True)
            try:
                os.chmod(base_dir, 0o700)
            except Exception:
                # chmod may fail on some OSes (Windows) — continue
                pass
        except Exception:
            logger.exception(
                "Não foi possível criar diretório seguro para WORM; usando cwd"
            )
            base_dir = os.getcwd()

        # Paths for immutable audit and processed sessions
        self.worm_path = os.path.join(base_dir, f"worm_audit_{self.service_name}.log")
        self.processed_sessions_path = os.path.join(
            base_dir, f"processed_sessions_{self.service_name}.jsonl"
        )

        # Ensure files exist with safe permissions (best-effort)
        try:
            open(self.worm_path, "a", encoding="utf-8").close()
            open(self.processed_sessions_path, "a", encoding="utf-8").close()
            try:
                os.chmod(self.worm_path, 0o600)
                os.chmod(self.processed_sessions_path, 0o600)
            except Exception:
                pass
        except Exception:
            logger.exception("Falha ao inicializar arquivos de auditoria/idempotencia")

        # Informational guidance for production
        if not getattr(Config, "BASE_DIR", None):
            logger.warning(
                "Config.BASE_DIR não definido: usando '%s'. Em produção, defina Config.BASE_DIR e proteja este diretório WORM.",
                base_dir,
            )
        self.air_gapped = False
        self.manual_override = False

    # -----------------------------
    # Auditing / Logging
    # -----------------------------
    def audit(
        self, event: str, level: str = "info", context: Optional[Dict[str, Any]] = None
    ):
        envelope = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "event": event,
            "level": level,
            "context": context or {},
        }
        try:
            # Structured local audit (WORM append)
            with open(self.worm_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(envelope, default=str, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Falha ao gravar WORM audit log")

        # Also send to global audit bus (best-effort)
        try:
            send_audit(event, level=level, context=envelope)
        except Exception:
            logger.debug("send_audit falhou, continuando")

    # -----------------------------
    # Idempotency / Exactly-once
    # -----------------------------
    def _session_record_exists(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            if not os.path.exists(self.processed_sessions_path):
                return None
            with open(self.processed_sessions_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("session_id") == session_id:
                            return obj
                    except Exception:
                        continue
        except Exception:
            logger.exception("Erro lendo processed_sessions")
        return None

    def _record_session_result(self, session_id: str, result: Dict[str, Any]):
        rec = {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }
        try:
            # Append atomically
            with open(self.processed_sessions_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Falha ao registrar sessão processada")

    # -----------------------------
    # Crypto / Sovereignty placeholders
    # -----------------------------
    def crypto_anchor(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Placeholder para ancoragem em DLT. Deve retornar um objeto com `anchor_id` e `public_proof`."""
        # In production, integrate with a DLT anchoring provider.
        anchor = {"anchor_id": f"anchor:{uuid.uuid4()}", "public_proof": None}
        self.audit("crypto_anchor", level="debug", context={"anchor": anchor})
        return anchor

    def pqc_encrypt(self, data: bytes) -> bytes:
        """Placeholder para encriptação pós-quântica. Retorna bytes encriptados (noop aqui)."""
        self.audit("pqc_encrypt", level="debug", context={"len": len(data)})
        return data

    def pqc_decrypt(self, data: bytes) -> bytes:
        self.audit("pqc_decrypt", level="debug", context={"len": len(data)})
        return data

    def zkp_validate_govbr(self, identity_payload: Dict[str, Any]) -> bool:
        """Placeholder para validação gov.br via ZKP. Retorna True/False."""
        self.audit(
            "zkp_validate_govbr",
            level="debug",
            context={"checked": bool(identity_payload)},
        )
        return True

    # -----------------------------
    # Resilience helpers
    # -----------------------------
    def circuit_breaker_check(self) -> bool:
        """Simples checker: se em modo manual_override False e air_gapped True, proibir saídas externas."""
        if self.manual_override:
            return True
        if self.air_gapped:
            # Only local operations allowed
            return False
        return True

    def chaos_inject(self, level: int = 0):
        """Inject latency or failures for testing (noop when level=0)."""
        if level <= 0:
            return
        # small, deterministic sleep to simulate latency
        time.sleep(min(0.1 * level, 2.0))

    # -----------------------------
    # Green FinOps (placeholder)
    # -----------------------------
    def estimate_carbon(self, inputs: Dict[str, Any]) -> Decimal:
        """Rudimentary carbon estimate: returns grams CO2 as Decimal."""
        # Very small deterministic estimate based on input size
        try:
            size = len(json.dumps(inputs, default=str))
            grams = Decimal(size) * Decimal("0.01")
            return grams.quantize(Decimal("0.01"))
        except Exception:
            return Decimal("0.00")

    # -----------------------------
    # Law-as-Code (minimal)
    # -----------------------------
    def legal_effective_value(self, key: str) -> Optional[Any]:
        """Minimal engine for law-derived constants. Extend with rule engine in production."""
        # Example: salario_minimo_2026
        if key == "salario_minimo_2026":
            return Decimal("1509.00")
        return None
