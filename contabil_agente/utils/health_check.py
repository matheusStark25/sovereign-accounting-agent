"""
Sistema de Health Checks Avançado
"""

import logging
import os
import sqlite3
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


def check_database(db_path: str) -> Dict[str, Any]:
    """Verifica saúde do banco de dados"""
    try:
        if not os.path.exists(db_path):
            return {"status": "unhealthy", "message": "Database não existe"}

        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]

            return {
                "status": "healthy",
                "sessions_count": count,
                "file_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 2),
            }
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_groq_api(api_key: str = None) -> Dict[str, Any]:
    """Verifica conectividade com Groq API"""
    try:
        if not api_key:
            api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            return {"status": "unhealthy", "message": "API key não configurada"}

        # Lazy import (Python 3.14 fix)
        try:
            from groq import Groq
        except Exception as import_err:
            logger.error(f"Erro ao importar Groq: {import_err}")
            return {"status": "unhealthy", "error": f"Import failed: {import_err}"}

        client = Groq(api_key=api_key)

        # Fazer request simples para testar
        start = time.time()
        client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        latency = round((time.time() - start) * 1000, 2)

        return {
            "status": "healthy",
            "latency_ms": latency,
            "model": "llama-3.1-8b-instant",
        }
    except Exception as e:
        logger.error(f"Groq API check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_disk_space(path: str = ".") -> Dict[str, Any]:
    """Verifica espaço em disco"""
    try:
        import shutil

        stat = shutil.disk_usage(path)

        free_gb = stat.free / (1024**3)
        total_gb = stat.total / (1024**3)
        used_percent = round((stat.used / stat.total) * 100, 2)

        status = "healthy"
        if free_gb < 1:
            status = "critical"
        elif free_gb < 5:
            status = "warning"

        return {
            "status": status,
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_percent": used_percent,
        }
    except Exception as e:
        logger.error(f"Disk space check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_memory() -> Dict[str, Any]:
    """Verifica uso de memória"""
    try:
        import psutil  # type: ignore

        mem = psutil.virtual_memory()

        status = "healthy"
        if mem.percent > 90:
            status = "critical"
        elif mem.percent > 80:
            status = "warning"

        return {
            "status": status,
            "used_percent": round(mem.percent, 2),
            "available_gb": round(mem.available / (1024**3), 2),
        }
    except ImportError:
        return {"status": "unknown", "message": "psutil não instalado"}
    except Exception as e:
        logger.error(f"Memory check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def deep_health_check(
    db_path: str = "db/sessions.db", api_key: str = None
) -> Dict[str, Any]:
    """Executa todos os health checks"""
    checks = {
        "database": check_database(db_path),
        "groq_api": check_groq_api(api_key),
        "disk_space": check_disk_space(),
        "memory": check_memory(),
    }

    # Determinar status geral
    statuses = [check["status"] for check in checks.values()]

    if "critical" in statuses or "unhealthy" in statuses:
        overall_status = "unhealthy"
    elif "warning" in statuses:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {"status": overall_status, "timestamp": time.time(), "checks": checks}
