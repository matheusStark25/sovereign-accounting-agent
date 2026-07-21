"""
Circuit breaker and retry logic for resilient external API calls.
"""

import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Estados possíveis do circuit breaker."""

    CLOSED = "closed"  # Funcionando normalmente
    OPEN = "open"  # Bloqueado por falhas
    HALF_OPEN = "half_open"  # Testando recuperação


class CircuitBreaker:
    """
    Circuit breaker pattern para proteção contra falhas em cascata.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Executa função com proteção do circuit breaker."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                logger.info("Circuit breaker: Tentando recuperação (HALF_OPEN)")
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(
                    f"Circuit breaker OPEN: aguarde {self._time_until_reset()}s"
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except self.expected_exception as e:
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Verifica se deve tentar resetar circuit."""
        if self.last_failure_time is None:
            return True

        return time.time() - self.last_failure_time >= self.recovery_timeout

    def _time_until_reset(self) -> int:
        """Tempo restante até tentar reset."""
        if self.last_failure_time is None:
            return 0

        elapsed = time.time() - self.last_failure_time
        return max(0, int(self.recovery_timeout - elapsed))

    def _on_success(self):
        """Callback em caso de sucesso."""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker: Recuperado (CLOSED)")
            self.state = CircuitState.CLOSED

    def _on_failure(self):
        """Callback em caso de falha."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            logger.info(
                f"Circuit breaker: Limite de falhas atingido ({self.failure_count}), mudando para OPEN"
            )
            self.state = CircuitState.OPEN


def with_circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exception: type = Exception,
):
    """
    Decorator para aplicar circuit breaker a funções.

    Uso:
        @with_circuit_breaker(failure_threshold=3, recovery_timeout=30)
        def chamar_api_externa():
            ...
    """
    breaker = CircuitBreaker(failure_threshold, recovery_timeout, expected_exception)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return breaker.call(f, *args, **kwargs)

        return decorated_function

    return decorator


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    expected_exception: type = Exception,
):
    """
    Decorator para retry com exponential backoff.

    Uso:
        @retry_with_backoff(max_attempts=5, initial_delay=2)
        def funcao_instavel():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return f(*args, **kwargs)

                except expected_exception as e:
                    last_exception = e

                    if attempt < max_attempts - 1:
                        logger.info(
                            f"Tentativa {attempt + 1}/{max_attempts} falhou: {e}. "
                            f"Aguardando {delay}s antes de retry..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"Todas {max_attempts} tentativas falharam")

            raise last_exception

        return decorated_function

    return decorator


class TimeoutExecutor:
    """Executa funções com timeout configurável."""

    @staticmethod
    def execute(func: Callable, timeout_seconds: int, *args, **kwargs) -> Any:
        """
        Executa função com timeout.

        Nota: Implementação simples. Para timeout real em produção,
        use threading.Thread ou multiprocessing.Process.
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError(f"Função excedeu timeout de {timeout_seconds}s")

        # Configura timeout (Unix only)
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)

            result = func(*args, **kwargs)

            signal.alarm(0)  # Cancela timeout
            return result

        except AttributeError:
            # Windows não suporta SIGALRM, executa sem timeout
            logger.warning("Timeout não suportado nesta plataforma (Windows)")
            return func(*args, **kwargs)
