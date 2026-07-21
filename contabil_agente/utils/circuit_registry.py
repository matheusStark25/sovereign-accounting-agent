from __future__ import annotations

from contabil_agente.utils.circuit_breaker import CircuitBreaker

# Global circuit breakers for key dependency domains
DB_CB = CircuitBreaker(max_failures=5, reset_timeout=60)
STORAGE_CB = CircuitBreaker(max_failures=5, reset_timeout=60)
EVENT_BUS_CB = CircuitBreaker(max_failures=5, reset_timeout=60)
CRYPTO_CB = CircuitBreaker(max_failures=5, reset_timeout=60)
