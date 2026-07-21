"""
Observability: metrics, tracing, and structured logging.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, Optional

from flask import g, request


class MetricsCollector:
    """Coletor de métricas compatível com Prometheus."""

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = defaultdict(float)
        self._histograms: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def increment(
        self, metric_name: str, value: int = 1, labels: Optional[Dict] = None
    ):
        """Incrementa contador."""
        key = self._build_key(metric_name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, metric_name: str, value: float, labels: Optional[Dict] = None):
        """Define valor de gauge."""
        key = self._build_key(metric_name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, metric_name: str, value: float, labels: Optional[Dict] = None):
        """Adiciona observação a histograma."""
        key = self._build_key(metric_name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def _build_key(self, metric_name: str, labels: Optional[Dict] = None) -> str:
        """Constrói chave única para métrica com labels."""
        if not labels:
            return metric_name

        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{metric_name}{{{label_str}}}"

    def get_metrics(self) -> Dict:
        """Retorna todas métricas no formato estruturado."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: {
                        "count": len(v),
                        "sum": sum(v),
                        "min": min(v) if v else 0,
                        "max": max(v) if v else 0,
                        "avg": sum(v) / len(v) if v else 0,
                    }
                    for k, v in self._histograms.items()
                },
            }

    def export_prometheus(self) -> str:
        """Exporta métricas no formato Prometheus."""
        lines = []

        with self._lock:
            # Counters
            for name, value in self._counters.items():
                lines.append(f"# TYPE {name.split('{')[0]} counter")
                lines.append(f"{name} {value}")

            # Gauges
            for name, value in self._gauges.items():
                lines.append(f"# TYPE {name.split('{')[0]} gauge")
                lines.append(f"{name} {value}")

            # Histograms (simplificado)
            for name, values in self._histograms.items():
                base_name = name.split("{")[0]
                lines.append(f"# TYPE {base_name} histogram")
                lines.append(f"{name}_count {len(values)}")
                lines.append(f"{name}_sum {sum(values)}")

        return "\n".join(lines)


# Instância global de métricas
_metrics = MetricsCollector()


def track_request_metrics(f):
    """
    Decorator para tracking de métricas de requisição.

    Métricas coletadas:
    - http_requests_total (counter)
    - http_request_duration_seconds (histogram)
    - http_requests_in_progress (gauge)
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()

        # Incrementa requests em progresso
        _metrics.set_gauge("http_requests_in_progress", 1)

        try:
            response = f(*args, **kwargs)
            status_code = response[1] if isinstance(response, tuple) else 200

            # Incrementa total de requests
            labels = {
                "method": request.method,
                "endpoint": request.endpoint or "unknown",
                "status": str(status_code),
            }
            _metrics.increment("http_requests_total", labels=labels)

            return response

        except Exception as e:
            # Tracking de erros
            labels = {
                "method": request.method,
                "endpoint": request.endpoint or "unknown",
                "status": "500",
                "error_type": type(e).__name__,
            }
            _metrics.increment("http_requests_total", labels=labels)
            _metrics.increment("http_errors_total", labels=labels)
            raise

        finally:
            # Observa duração
            duration = time.time() - start_time
            labels = {
                "method": request.method,
                "endpoint": request.endpoint or "unknown",
            }
            _metrics.observe("http_request_duration_seconds", duration, labels=labels)

            # Decrementa requests em progresso
            _metrics.set_gauge("http_requests_in_progress", 0)

    return decorated_function


class StructuredLogger:
    """Logger estruturado em JSON para melhor observabilidade."""

    def __init__(self, name: str = "app"):
        self.logger = logging.getLogger(name)
        self._configure()

    def _configure(self):
        """Configura formato estruturado."""
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def _build_log_entry(self, level: str, message: str, **kwargs) -> str:
        """Constrói entrada de log estruturada."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }

        # Adiciona contexto da requisição se disponível
        if request:
            entry["request"] = {
                "method": request.method,
                "path": request.path,
                "remote_addr": request.remote_addr,
                "user_agent": request.headers.get("User-Agent", "unknown"),
            }

        # Adiciona contexto do usuário se disponível
        if hasattr(g, "empresa_id"):
            entry["empresa_id"] = g.empresa_id

        return json.dumps(entry, ensure_ascii=False)

    def info(self, message: str, **kwargs):
        """Log nível INFO."""
        self.logger.info(self._build_log_entry("INFO", message, **kwargs))

    def warning(self, message: str, **kwargs):
        """Log nível WARNING."""
        self.logger.warning(self._build_log_entry("WARNING", message, **kwargs))

    def error(self, message: str, **kwargs):
        """Log nível ERROR."""
        self.logger.error(self._build_log_entry("ERROR", message, **kwargs))

    def debug(self, message: str, **kwargs):
        """Log nível DEBUG."""
        self.logger.debug(self._build_log_entry("DEBUG", message, **kwargs))


class RequestTracer:
    """Simple distributed tracing."""

    @staticmethod
    def generate_trace_id() -> str:
        """Gera ID único para trace."""
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def trace_request(f):
        """Decorator para adicionar tracing a requests."""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Gera ou usa trace ID existente
            trace_id = request.headers.get(
                "X-Trace-Id", RequestTracer.generate_trace_id()
            )
            g.trace_id = trace_id

            # Adiciona ao response header
            response = f(*args, **kwargs)

            if isinstance(response, tuple):
                data, status = response[0], response[1]
                headers = response[2] if len(response) > 2 else {}
            else:
                data, status, headers = response, 200, {}

            headers["X-Trace-Id"] = trace_id

            return data, status, headers

        return decorated_function


def get_metrics_collector() -> MetricsCollector:
    """Retorna instância global do coletor de métricas."""
    return _metrics
