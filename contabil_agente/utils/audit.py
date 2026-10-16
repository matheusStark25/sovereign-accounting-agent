"""
Módulo de Auditoria em Tempo Real
Registra eventos do sistema para governança e monitoramento
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict

Config = None
try:
    from contabil_agente.core.config import Config
except Exception:
    try:
        from core.config import Config
    except Exception:
        # Create minimal Config stub if imports fail
        class Config:
            """Stub Config class when core.config is unavailable"""

            @staticmethod
            def get(key: str, default=None):
                return os.environ.get(key, default)


logger = logging.getLogger(__name__)

_audit_lock = threading.Lock()


def send_audit(message: str, level: str = "info", context: Dict = None):
    """
    Grava evento de auditoria em tempo real

    Args:
        message: Mensagem descritiva do evento
        level: Nível (info, warning, error)
        context: Contexto adicional (dict)
    """
    try:
        evt = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "level": level,
            "context": context or {},
        }

        logs_dir = Config.LOGS_DIR
        os.makedirs(logs_dir, exist_ok=True)
        evol_path = os.path.join(logs_dir, "evolucao_sistema.json")

        with _audit_lock:
            if os.path.exists(evol_path):
                try:
                    with open(evol_path, "r", encoding="utf-8") as f:
                        arr = json.load(f)
                except Exception:
                    arr = []
            else:
                arr = []

            arr.append(evt)
            arr = arr[-5000:]  # mantém últimos 5000 eventos

            try:
                with open(evol_path, "w", encoding="utf-8") as f:
                    json.dump(arr, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # Log no sistema padrão
        if level == "error":
            logger.error(f"AUDIT: {message} | {context}")
        else:
            logger.info(f"AUDIT: {message} | {context}")

        # Emite via Socket.IO se disponível
        try:
            # Import dinâmico para evitar dependência circular
            import sys

            if "socketio" in sys.modules:
                socketio = sys.modules.get("socketio")
                if socketio is not None:
                    socketio.emit("audit_event", evt, broadcast=True)
        except Exception:
            logger.debug("SocketIO emit failed or not initialized")

    except Exception:
        logger.exception("Falha ao gravar evento de auditoria")


def register_document_hash_in_governance(
    filename: str, sha256: str, metadata: Dict = None
) -> bool:
    """
    Tenta registrar hash de documento no registry de governança

    Args:
        filename: Nome do arquivo
        sha256: Hash SHA-256 do documento
        metadata: Metadados adicionais

    Returns:
        True se registro bem-sucedido
    """
    try:
        # Import dinâmico para evitar dependência circular
        try:
            from contabil_agente.orchestrator.universal_orchestrator import (
                get_orchestrator,
            )
        except Exception:
            try:
                from ..orchestrator.universal_orchestrator import get_orchestrator
            except Exception:
                # Ensure project root is on sys.path and retry absolute import
                import sys
                from pathlib import Path

                project_root = Path(__file__).resolve().parents[2]
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from contabil_agente.orchestrator.universal_orchestrator import (
                    get_orchestrator,
                )

        orchestrator = get_orchestrator()
        gov = getattr(orchestrator, "governanca", None)

        if gov and isinstance(gov, dict) and "document_registry" in gov:
            success = gov["document_registry"].register_hash(
                filename, sha256, metadata or {}
            )

            if success:
                send_audit(
                    "Hash de documento registrado",
                    level="info",
                    context={
                        "tool": "hash",
                        "status": "registered",
                        "filename": filename,
                        "hash": sha256[:12],
                    },
                )

                # Emite evento específico de hash
                try:
                    import sys

                    if "socketio" in sys.modules:
                        socketio = sys.modules.get("socketio")
                        if socketio is not None:
                            socketio.emit(
                                "tool_hash_registered",
                                {
                                    "timestamp": datetime.now().isoformat(),
                                    "status": "registered",
                                    "filename": filename,
                                    "hash_prefix": sha256[:12],
                                },
                                broadcast=True,
                            )
                except Exception:
                    pass

            return success

    except Exception:
        logger.exception("Erro ao tentar registrar hash no governance")

    return False
