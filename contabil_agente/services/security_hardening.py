"""Aggregator for the security hardening subsystems.

Expose `init_hardening(app, base_path, db)` to wire lightweight
components (honeypot, operator shield, chaos engine, audit anchoring,
postquantum store). Keep initialization safe and idempotent.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("security_hardening")

try:
    from contabil_agente.services.honeypot import setup_honeypot, check_honeypot_access
    from contabil_agente.services.operator_shield import OperatorShield
    from contabil_agente.services.chaos_engine import ChaosEngine
    from contabil_agente.services.blockchain_audit import (
        append_audit,
        compute_rolling_root,
    )
    from contabil_agente.services.postquantum_store import PQStore
except Exception:
    setup_honeypot = None
    check_honeypot_access = None
    OperatorShield = None
    ChaosEngine = None
    append_audit = None
    compute_rolling_root = None
    PQStore = None


_shield = None
_chaos = None
_pq = None


def init_hardening(base_path: Optional[str] = None, db=None):
    global _shield, _chaos, _pq
    base = base_path or os.getenv("STARK_BASE_PATH", "./stark_data")
    try:
        if setup_honeypot:
            setup_honeypot(base)
    except Exception:
        logger.exception("honeypot_init_failed")

    try:
        if OperatorShield and _shield is None:
            _shield = OperatorShield()
            _shield.start()
    except Exception:
        logger.exception("operator_shield_failed")

    try:
        if ChaosEngine and _chaos is None:
            _chaos = ChaosEngine()
            _chaos.start()
    except Exception:
        logger.exception("chaos_engine_failed")

    try:
        # instantiate PQStore but don't require PQ key; allow fallback
        if PQStore:
            _pq = PQStore()
    except Exception:
        logger.exception("pq_store_failed")

    # record init in audit trail if available
    try:
        if append_audit:
            append_audit({"evt": "hardening_init", "base": base})
    except Exception:
        logger.exception("audit_append_failed")


def shutdown_hardening():
    # no assignment here; simply reference module-level objects
    try:
        if _shield:
            _shield.stop()
    except Exception:
        pass
    try:
        if _chaos:
            _chaos.stop()
    except Exception:
        pass


__all__ = ["init_hardening", "shutdown_hardening"]
