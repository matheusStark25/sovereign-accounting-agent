"""Services - Camada de lógica de negócio
This module is a stability guard for service imports.

It implements lazy, guarded imports so that missing optional
dependencies do not break package import (boot resilience).

Usage patterns:
- Use `get_<service>_class()` to obtain the service class (lazy-loaded).
- `check_core_health()` returns READY/MISSING for each registered service.
"""

import importlib
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Professional metadata
__version__ = "1.0.0"
__author__ = "Equipe Contabil Agente"
__maintainer__ = "DevOps / Plataforma"


class ServiceRegistry:
    """Registry that holds lazy loaders and status for services.

    Services are registered with the module path and attribute name. They are
    only imported when first requested via `load(name)`. Successful loads
    are cached in module globals to behave like normal imports afterwards.
    """

    def __init__(self):
        self._entries: Dict[str, Dict[str, Any]] = {}

    def register(
        self, key: str, module_path: str, attr_name: str, essential: bool = False
    ) -> None:
        self._entries[key] = {
            "module": module_path,
            "attr": attr_name,
            "essential": essential,
            "loaded": False,
            "error": None,
        }

    def load(self, key: str) -> Optional[type]:
        entry = self._entries.get(key)
        if not entry:
            return None

        if entry["loaded"]:
            return globals().get(entry["attr"])

        try:
            mod = importlib.import_module(entry["module"])
            attr = getattr(mod, entry["attr"], None)
            if attr is None:
                raise AttributeError(f"{entry['attr']} not found in {entry['module']}")

            # Cache into module globals for convenience and expose in __all__
            globals()[entry["attr"]] = attr
            entry["loaded"] = True
            entry["error"] = None

            # set availability flag, e.g. CHATSERVICE_AVAILABLE
            flag_name = f"{entry['attr'].upper()}_AVAILABLE"
            globals()[flag_name] = True

            if entry["attr"] not in __all__:
                __all__.append(entry["attr"])

            logger.debug("Loaded service %s from %s", entry["attr"], entry["module"])
            return attr
        except Exception as exc:  # pragma: no cover - defensive boot
            entry["loaded"] = False
            entry["error"] = str(exc)
            flag_name = f"{entry['attr'].upper()}_AVAILABLE"
            globals()[flag_name] = False
            logger.warning("Service %s not available: %s", key, exc)
            return None

    def status(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        for k, v in self._entries.items():
            out[k] = {
                "loaded": v["loaded"],
                "essential": v["essential"],
                "error": v["error"],
            }
        return out


# Initialize registry and availability flags (default False)
registry = ServiceRegistry()

# Register services lazily. Mark essential ones accordingly.
registry.register(
    "chat", "contabil_agente.services.chat_service", "ChatService", essential=False
)
registry.register(
    "document",
    "contabil_agente.services.document_service",
    "DocumentService",
    essential=False,
)
registry.register(
    "ingestao",
    "contabil_agente.services.ingestao_service",
    "IngestaoService",
    essential=True,
)
registry.register(
    "data_extraction_error",
    "contabil_agente.services.ingestao_service",
    "DataExtractionError",
    essential=False,
)
registry.register(
    "session",
    "contabil_agente.services.session_service",
    "SessionService",
    essential=True,
)

# Availability flags (set to False until a successful load)
CHATSERVICE_AVAILABLE = False
DOCUMENTSERVICE_AVAILABLE = False
INGESTAOSERVICE_AVAILABLE = False
DATAEXTRACTIONERROR_AVAILABLE = False
SESSIONSERVICE_AVAILABLE = False


def _load_to_alias(key: str):
    """Helper to load a service and return its class or None."""
    attr = registry.load(key)
    return attr


def get_chat_service_class():
    """Return `ChatService` class if available, else None (lazy load)."""
    return _load_to_alias("chat")


def get_document_service_class():
    return _load_to_alias("document")


def get_ingestao_service_class():
    return _load_to_alias("ingestao")


def get_data_extraction_error():
    return _load_to_alias("data_extraction_error")


def get_session_service_class():
    return _load_to_alias("session")


def check_core_health() -> Dict[str, Any]:
    """Return aggregated health for registered services.

    The function never raises; it logs missing essential services clearly.
    """
    status = registry.status()
    report = {}
    for key, info in status.items():
        report[key] = "READY" if info["loaded"] else "MISSING"
        if info["essential"] and not info["loaded"]:
            logger.error("Essential service missing at boot: %s", key)
    return report


# Construct minimal exports: helpers and metadata. When services are loaded,
# their class names are appended to __all__ dynamically.
__all__ = [
    "get_chat_service_class",
    "get_document_service_class",
    "get_ingestao_service_class",
    "get_data_extraction_error",
    "get_session_service_class",
    "check_core_health",
    "registry",
    "__version__",
    "__author__",
    "__maintainer__",
]
