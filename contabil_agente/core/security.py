"""
Módulo de segurança e proteções
Sanitização de entrada, Circuit Breaker, validações
"""

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


def sanitizar_input(texto: str) -> str:
    """Bloqueia termos comuns de prompt injection"""
    if not isinstance(texto, str):
        raise ValueError("Entrada inválida")

    texto_limpo = texto.strip()
    texto_lower = texto_limpo.lower()

    termos_bloqueados = [
        "ignore previous",
        "system:",
        "you are chatgpt",
        "###",
        "```",
        "role: system",
        "prompt injection",
        "execute",
        "rm -r",
        "shutdown",
        "format c:",
    ]

    if any(t in texto_lower for t in termos_bloqueados):
        raise ValueError("Entrada rejeitada por segurança")

    return texto_limpo


class CircuitBreaker:
    """
    Circuit Breaker profissional para proteção de chamadas externas
    Evita sobrecarga quando serviços externos falham
    """

    def __init__(self, failure_threshold=3, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit breaker is OPEN")

            try:
                result = func(*args, **kwargs)
                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    self.failures = 0
                return result
            except Exception:
                self.failures += 1
                self.last_failure_time = time.time()
                if self.failures >= self.failure_threshold:
                    self.state = "OPEN"
                    logger.error(f"Circuit breaker aberto para {func.__name__}")
                raise

        return wrapper
