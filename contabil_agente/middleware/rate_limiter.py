"""
Rate limiting robusto por API key, empresa e IP.
Suporta múltiplos backends (memória, Redis).
"""

import os
import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Dict, Optional, Tuple, List

from flask import g, jsonify, request


class RateLimiter:
    """
    Rate limiter thread-safe com suporte a múltiplas estratégias.
    """

    def __init__(self, backend="memory"):
        self.backend = backend
        self._memory_store: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

        # Configurações padrão (podem ser sobrescritas por env vars)
        self.limits = {
            "per_ip": {
                "requests": int(os.getenv("RATE_LIMIT_IP_REQUESTS", "60")),
                "window": int(os.getenv("RATE_LIMIT_IP_WINDOW", "60")),  # 60 req/min
            },
            "per_api_key": {
                "requests": int(os.getenv("RATE_LIMIT_API_REQUESTS", "1000")),
                "window": int(
                    os.getenv("RATE_LIMIT_API_WINDOW", "3600")
                ),  # 1000 req/hora
            },
            "per_empresa": {
                "requests": int(os.getenv("RATE_LIMIT_EMPRESA_REQUESTS", "500")),
                "window": int(
                    os.getenv("RATE_LIMIT_EMPRESA_WINDOW", "3600")
                ),  # 500 req/hora
            },
        }

    def _get_key(self, identifier: str, limit_type: str) -> str:
        """Gera chave única para o rate limit."""
        return f"ratelimit:{limit_type}:{identifier}"

    def _check_limit_memory(
        self, key: str, max_requests: int, window: int
    ) -> Tuple[bool, int]:
        """Verifica rate limit usando memória (thread-safe)."""
        now = time.time()

        with self._lock:
            # Remove requisições antigas
            self._memory_store[key] = [
                ts for ts in self._memory_store[key] if now - ts < window
            ]

            current_count = len(self._memory_store[key])

            if current_count >= max_requests:
                # Calcula tempo até reset
                oldest = (
                    min(self._memory_store[key]) if self._memory_store[key] else now
                )
                retry_after = int(window - (now - oldest))
                return False, retry_after

            # Adiciona nova requisição
            self._memory_store[key].append(now)
            return True, 0

    def check_limit(
        self, identifier: str, limit_type: str = "per_ip"
    ) -> Tuple[bool, int]:
        """
        Verifica se o identificador está dentro do rate limit.

        Returns:
            (allowed: bool, retry_after: int)
        """
        if limit_type not in self.limits:
            return True, 0

        config = self.limits[limit_type]
        key = self._get_key(identifier, limit_type)

        if self.backend == "memory":
            return self._check_limit_memory(key, config["requests"], config["window"])

        # Adicionar suporte para Redis aqui se necessário
        return True, 0

    def reset(self, identifier: str, limit_type: str = "per_ip"):
        """Reseta contador para um identificador."""
        key = self._get_key(identifier, limit_type)
        with self._lock:
            if key in self._memory_store:
                del self._memory_store[key]

    def reset_all(self, limit_type: Optional[str] = None) -> List[str]:
        """Reseta os contadores.

        - Se `limit_type` for fornecido, reseta apenas os contadores daquele tipo
          (ex.: 'per_ip').
        - Se `limit_type` for None, reseta todos os contadores.

        Retorna a lista de chaves removidas (útil para debug/testes).
        """
        deleted: List[str] = []
        with self._lock:
            if limit_type:
                prefix = f"ratelimit:{limit_type}:"
                keys_to_delete = [
                    k for k in list(self._memory_store.keys()) if k.startswith(prefix)
                ]
                for k in keys_to_delete:
                    deleted.append(k)
                    del self._memory_store[k]
            else:
                # remover tudo de forma atômica
                deleted = list(self._memory_store.keys())
                self._memory_store.clear()

        return deleted


# Instância global do rate limiter
_rate_limiter = RateLimiter()


def rate_limit(limit_type: str = "per_ip", custom_identifier: Optional[str] = None):
    """
    Decorator para aplicar rate limiting em endpoints.

    Args:
        limit_type: 'per_ip', 'per_api_key', ou 'per_empresa'
        custom_identifier: Identificador customizado (opcional)

    Uso:
        @app.route('/api/endpoint')
        @rate_limit('per_api_key')
        def endpoint():
            return jsonify({"ok": True})
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Exempt health checks from rate limiting to avoid 429 from polling
            try:
                p = request.path or ""
                if p.startswith("/api/health") or p.startswith("/health"):
                    return f(*args, **kwargs)
            except Exception:
                # If request is not available for some reason, proceed with normal checks
                pass
            # Determina identificador baseado no tipo
            if custom_identifier:
                identifier = custom_identifier
            elif limit_type == "per_ip":
                identifier = request.remote_addr or "unknown"
            elif limit_type == "per_api_key":
                identifier = request.headers.get("X-API-Key", "no_key")
            elif limit_type == "per_empresa":
                identifier = getattr(g, "empresa_id", "no_empresa")
            else:
                identifier = request.remote_addr or "unknown"

            # Verifica rate limit
            allowed, retry_after = _rate_limiter.check_limit(identifier, limit_type)

            if not allowed:
                return (
                    jsonify(
                        {
                            "erro": "Rate limit excedido",
                            "detalhes": f"Limite de {_rate_limiter.limits[limit_type]['requests']} requisições por {_rate_limiter.limits[limit_type]['window']}s excedido",
                            "retry_after": retry_after,
                            "status": "rate_limit_exceeded",
                        }
                    ),
                    429,
                )

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def get_rate_limiter() -> RateLimiter:
    """Retorna instância do rate limiter para uso direto."""
    return _rate_limiter
