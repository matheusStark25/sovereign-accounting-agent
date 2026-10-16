"""Backend application and infrastructure moved from contabil_agente.agent_contabil.

This module exposes `app` (Flask application) plus infra objects like
`_vault`, `_audit_logger`, `_start_cleanup`, `_graceful_shutdown`, and
`_intelligence` so other modules can import them from a single location.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import signal
import threading
import time
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger("contabil_agente.backend.app")

# --- Group D integrations (settings/vault/audit) ---
try:
    from contabil_agente.core.settings import settings
except Exception:
    settings = None

try:
    from contabil_agente.core.vault_client import VaultClient
    from contabil_agente.governance.audit import AuditLogger
except Exception:
    VaultClient = None  # type: ignore
    AuditLogger = None  # type: ignore

try:
    from contabil_agente.resilience.cleanup import CleanupService
    from contabil_agente.resilience.readiness import readiness_check
except Exception:
    CleanupService = None  # type: ignore
    readiness_check = None  # type: ignore

# initialize vault and audit logger (best-effort)
_vault = None
_audit_logger = None
if VaultClient is not None and settings is not None:
    try:
        _vault = VaultClient(
            url=getattr(settings, "VAULT_ADDR", None),
            token=getattr(settings, "VAULT_TOKEN", None),
        )
    except Exception:
        logger.exception(
            "Vault client initialization failed; continuing in degraded mode"
        )

    hmac_key_raw = None
    try:
        if _vault is not None:
            hmac_key_raw = _vault.get_secret("hmac_key_v1")
    except Exception:
        hmac_key_raw = None

    if not hmac_key_raw:
        hmac_key_raw = os.getenv("AUDIT_HMAC_KEY")

    if hmac_key_raw and AuditLogger is not None:
        try:
            key_bytes = (
                hmac_key_raw.encode("utf-8")
                if isinstance(hmac_key_raw, str)
                else hmac_key_raw
            )
            _audit_logger = AuditLogger(path=None, hmac_key=key_bytes)
            logger.info("AuditLogger initialized with HMAC key")
        except Exception:
            logger.exception("Failed to initialize AuditLogger from HMAC key")

# start cleanup background thread
_cleanup_service = None
_cleanup_thread = None


def _start_cleanup():
    global _cleanup_service, _cleanup_thread
    if CleanupService is None:
        return
    try:
        _cleanup_service = CleanupService(
            retention_hours=(
                getattr(settings, "RETENTION_HOURS", 24) if settings else 24
            ),
            audit=_audit_logger,
        )

        def _loop():
            while True:
                try:
                    _cleanup_service.run_pass()
                except Exception:
                    logger.exception("Cleanup pass failed")
                time.sleep(60)

        _cleanup_thread = threading.Thread(target=_loop, daemon=True)
        _cleanup_thread.start()
        logger.info("CleanupService background thread started")
    except Exception:
        logger.exception("Failed starting CleanupService background thread")


def _graceful_shutdown(signum, frame):
    logger.info("Graceful shutdown signal received: %s", signum)
    try:
        import traceback
        import sys

        outp = {
            "ts": datetime.now(UTC).isoformat(),
            "signum": int(signum) if isinstance(signum, int) else str(signum),
            "pid": os.getpid(),
        }
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            traces_dir = os.path.join(repo_root, "shutdown_traces")
            os.makedirs(traces_dir, exist_ok=True)
            fn = os.path.join(traces_dir, f"shutdown_trace_{int(time.time())}.log")
        except Exception:
            fn = os.path.join(os.getcwd(), f"shutdown_trace_{int(time.time())}.log")

        try:
            fh = open(fn, "w", encoding="utf-8")
        except Exception:
            fh = None
        if fh:
            try:
                fh.write(json.dumps(outp, ensure_ascii=False) + "\n")
                try:
                    traceback.print_stack(frame, file=fh)
                except Exception:
                    fh.write("Failed to print stack from frame\n")
                try:
                    fh.write("Current threads:\n")
                    for tid, fobj in sys._current_frames().items():
                        fh.write(f"Thread {tid}:\n")
                        traceback.print_stack(fobj, file=fh)
                except Exception:
                    fh.write("Failed to dump thread frames\n")
            finally:
                try:
                    fh.flush()
                except Exception:
                    pass
                try:
                    fh.close()
                except Exception:
                    pass
            logger.info("Wrote shutdown trace to %s", fn)
    except Exception:
        logger.exception("Failed writing shutdown trace")
    try:
        if _vault is not None:
            try:
                _vault.shutdown()
            except Exception:
                logger.exception("Vault shutdown failed")
        if _cleanup_service is not None:
            try:
                _cleanup_service.run_pass()
            except Exception:
                logger.exception("CleanupService final pass failed")
    except Exception:
        logger.exception("Error during graceful shutdown")
    try:
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass
    except Exception:
        pass


# Prefer canonical Flask application from existing app modules
try:
    from contabil_agente.app_api import app  # type: ignore
except Exception:
    try:
        from contabil_agente.app import app as legacy_app  # type: ignore

        app = legacy_app
    except Exception:
        app = None


# Register readiness and metrics endpoints on the Flask app if available
if app is not None:
    try:
        from flask import jsonify, request
    except Exception:
        jsonify = None

    if jsonify is not None:

        @app.route("/v1/health/ready", methods=["GET"])
        def _health_ready():
            try:
                services = {}
                if _vault is not None:
                    services["vault"] = _vault
                try:
                    import redis as _redis_mod

                    if getattr(settings, "REDIS_URL", None):
                        try:
                            redis_client = _redis_mod.from_url(
                                getattr(settings, "REDIS_URL")
                            )
                            services["redis"] = redis_client
                        except Exception:
                            services["redis"] = None
                except Exception:
                    pass
                if readiness_check is not None:
                    out = readiness_check(services)
                    return jsonify(out), 200 if out.get("status") == "ready" else 503
                return jsonify({"status": "ready"}), 200
            except Exception:
                logger.exception("readiness handler failed")
                return jsonify({"status": "unavailable"}), 503

        @app.route("/v1/metrics", methods=["GET"])
        def _metrics():
            try:
                try:
                    from contabil_agente.chat_refactored import (
                        metrics_endpoint as _metrics_fn,
                    )
                except Exception:
                    _metrics_fn = None
                token = request.args.get("token") or request.headers.get(
                    "Authorization"
                )
                if _metrics_fn:
                    try:
                        text = _metrics_fn(token)
                        return text, 200, {"Content-Type": "text/plain; charset=utf-8"}
                    except PermissionError:
                        return jsonify({"error": "unauthorized"}), 401
                    except Exception:
                        logger.exception("metrics endpoint failed")
                        return jsonify({"error": "metrics_failed"}), 503
                stats = {"uptime_seconds": int(time.time())}
                return jsonify(stats), 200
            except Exception:
                logger.exception("metrics handler crash")
                return jsonify({"error": "internal"}), 500

    try:
        _start_cleanup()
    except Exception:
        logger.exception("Failed to start cleanup from app bootstrap")


# --- Group E: Intelligence Orchestrator (FSM, deterministic scoring, forensic audit)
IntelligenceOrchestrator = None
try:
    orchestrator_module = importlib.import_module("intelligence.orchestrator")
    IntelligenceOrchestrator = getattr(
        orchestrator_module, "IntelligenceOrchestrator", None
    )
except Exception:
    IntelligenceOrchestrator = None

_intelligence: Optional[Any] = None
if IntelligenceOrchestrator is not None:
    try:
        _intelligence = IntelligenceOrchestrator()
        logger.info("IntelligenceOrchestrator initialized (Group E)")
    except Exception:
        logger.exception("Failed to initialize IntelligenceOrchestrator")

# --- Agent plugin loader -------------------------------------------------
agents: dict[str, Any] = {}


def _load_agents_from_config():
    """Load agent instances based on environment configuration.

    The environment variable `AGENTS` may contain a comma-separated list
    of agent names to enable (defaults to `contabilidade,demo`). Known
    agents are mapped in `registry` to their import path and class name.
    """
    cfg = os.getenv("AGENTS", "contabilidade,demo")
    desired = [s.strip() for s in cfg.split(",") if s.strip()]

    registry = {
        "contabilidade": ("contabil_agente.agent", "AgenteContabil"),
        "demo": ("agents.demo.agent", "DemoAgent"),
    }

    for name in desired:
        if name in agents:
            continue
        entry = registry.get(name)
        if not entry:
            logger.warning("Unknown agent '%s' in AGENTS; skipping", name)
            continue
        module_path, class_name = entry
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name, None)
            if cls is None:
                logger.warning(
                    "Agent class %s not found in %s", class_name, module_path
                )
                continue
            inst = cls()
            agents[name] = inst
            logger.info("Loaded agent '%s' from %s", name, module_path)
        except Exception:
            logger.exception("Failed to load agent %s from %s", name, module_path)


# If a Flask app is present, register discovery and routing endpoints
if app is not None:
    try:
        from flask import request, jsonify  # type: ignore

        _load_agents_from_config()

        @app.route("/v1/agents", methods=["GET"])
        def _list_agents():
            try:
                out = []
                for name, inst in agents.items():
                    try:
                        meta = (
                            inst.get_metadata() if hasattr(inst, "get_metadata") else {}
                        )
                    except Exception:
                        meta = {}
                    out.append({"name": name, "metadata": meta})
                return jsonify({"agents": out}), 200
            except Exception:
                logger.exception("agents listing failed")
                return jsonify({"error": "internal"}), 500

        @app.route("/v1/chat/<agent_name>", methods=["POST"])
        def _chat_agent(agent_name: str):
            try:
                payload = request.get_json(silent=True) or {}
                agent = agents.get(agent_name)
                if agent is None:
                    return (
                        jsonify(
                            {"error": "unknown_agent", "available": list(agents.keys())}
                        ),
                        404,
                    )
                # payload can be raw input or a dict with keys `input` and `context`
                input_body = payload.get("input", payload)
                context = payload.get("context") if isinstance(payload, dict) else None
                try:
                    result = agent.process(input_body, context=context)
                except TypeError:
                    # agent may implement older signature process(input)
                    result = agent.process(input_body)
                return jsonify(result), 200
            except Exception:
                logger.exception("agent chat handler failed")
                return jsonify({"error": "internal"}), 500

    except Exception:
        logger.exception("Failed registering agent routes")

__all__ = [
    "app",
    "_vault",
    "_audit_logger",
    "_start_cleanup",
    "_graceful_shutdown",
    "_intelligence",
    "agents",
]
