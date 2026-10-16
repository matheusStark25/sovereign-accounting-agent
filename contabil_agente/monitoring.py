"""
SISTEMA DE MONITORAMENTO PROFISSIONAL
Prometheus + Grafana ready
"""

import json
import time
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any, Dict

import psutil


class MetricsCollector:
    """Coletor de métricas para monitoramento"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "documents_generated": 0,
            "calculations_performed": 0,
            "average_response_time": 0,
            "active_sessions": 0,
        }

        # Histórico de métricas
        self.response_times = deque(maxlen=max_history)
        self.error_log = deque(maxlen=100)
        self.request_history = deque(maxlen=max_history)

        # Lock para thread-safety
        self.lock = Lock()

        # Timestamp de início
        self.start_time = time.time()

    def record_request(self, success: bool = True, response_time: float = 0):
        """Registra uma requisição"""
        with self.lock:
            self.metrics["requests_total"] += 1
            if success:
                self.metrics["requests_success"] += 1
            else:
                self.metrics["requests_error"] += 1

            if response_time > 0:
                self.response_times.append(response_time)
                # Recalcula média
                if self.response_times:
                    self.metrics["average_response_time"] = sum(
                        self.response_times
                    ) / len(self.response_times)

            self.request_history.append(
                {
                    "timestamp": time.time(),
                    "success": success,
                    "response_time": response_time,
                }
            )

    def record_document_generated(self, doc_type: str):
        """Registra geração de documento"""
        with self.lock:
            self.metrics["documents_generated"] += 1

    def record_calculation(self, calc_type: str):
        """Registra cálculo realizado"""
        with self.lock:
            self.metrics["calculations_performed"] += 1

    def record_error(self, error_type: str, error_message: str):
        """Registra erro"""
        with self.lock:
            self.error_log.append(
                {"timestamp": time.time(), "type": error_type, "message": error_message}
            )

    def update_active_sessions(self, count: int):
        """Atualiza número de sessões ativas"""
        with self.lock:
            self.metrics["active_sessions"] = count

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas atuais"""
        with self.lock:
            # Métricas de sistema
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Uptime
            uptime_seconds = time.time() - self.start_time

            # Taxa de erro
            error_rate = 0
            if self.metrics["requests_total"] > 0:
                error_rate = (
                    self.metrics["requests_error"] / self.metrics["requests_total"]
                ) * 100

            # Requests por minuto (últimos 60 segundos)
            current_time = time.time()
            recent_requests = [
                r for r in self.request_history if current_time - r["timestamp"] < 60
            ]
            requests_per_minute = len(recent_requests)

            return {
                # Métricas de aplicação
                "application": {
                    "requests_total": self.metrics["requests_total"],
                    "requests_success": self.metrics["requests_success"],
                    "requests_error": self.metrics["requests_error"],
                    "error_rate_percent": round(error_rate, 2),
                    "requests_per_minute": requests_per_minute,
                    "documents_generated": self.metrics["documents_generated"],
                    "calculations_performed": self.metrics["calculations_performed"],
                    "average_response_time_ms": round(
                        self.metrics["average_response_time"] * 1000, 2
                    ),
                    "active_sessions": self.metrics["active_sessions"],
                },
                # Métricas de sistema
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_used_mb": round(memory.used / 1024 / 1024, 2),
                    "memory_available_mb": round(memory.available / 1024 / 1024, 2),
                    "disk_percent": disk.percent,
                    "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 2),
                    "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
                },
                # Informações gerais
                "info": {
                    "uptime_seconds": int(uptime_seconds),
                    "uptime_formatted": self._format_uptime(uptime_seconds),
                    "timestamp": datetime.now().isoformat(),
                },
            }

    def get_prometheus_metrics(self) -> str:
        """Retorna métricas no formato Prometheus"""
        metrics = self.get_metrics()

        lines = [
            "# HELP agente_dp_requests_total Total de requisições",
            "# TYPE agente_dp_requests_total counter",
            f"agente_dp_requests_total {metrics['application']['requests_total']}",
            "",
            "# HELP agente_dp_requests_success Requisições com sucesso",
            "# TYPE agente_dp_requests_success counter",
            f"agente_dp_requests_success {metrics['application']['requests_success']}",
            "",
            "# HELP agente_dp_requests_error Requisições com erro",
            "# TYPE agente_dp_requests_error counter",
            f"agente_dp_requests_error {metrics['application']['requests_error']}",
            "",
            "# HELP agente_dp_error_rate_percent Taxa de erro em porcentagem",
            "# TYPE agente_dp_error_rate_percent gauge",
            f"agente_dp_error_rate_percent {metrics['application']['error_rate_percent']}",
            "",
            "# HELP agente_dp_documents_generated Total de documentos gerados",
            "# TYPE agente_dp_documents_generated counter",
            f"agente_dp_documents_generated {metrics['application']['documents_generated']}",
            "",
            "# HELP agente_dp_calculations_performed Total de cálculos realizados",
            "# TYPE agente_dp_calculations_performed counter",
            f"agente_dp_calculations_performed {metrics['application']['calculations_performed']}",
            "",
            "# HELP agente_dp_response_time_ms Tempo médio de resposta em ms",
            "# TYPE agente_dp_response_time_ms gauge",
            f"agente_dp_response_time_ms {metrics['application']['average_response_time_ms']}",
            "",
            "# HELP agente_dp_active_sessions Sessões ativas",
            "# TYPE agente_dp_active_sessions gauge",
            f"agente_dp_active_sessions {metrics['application']['active_sessions']}",
            "",
            "# HELP agente_dp_cpu_percent Uso de CPU em porcentagem",
            "# TYPE agente_dp_cpu_percent gauge",
            f"agente_dp_cpu_percent {metrics['system']['cpu_percent']}",
            "",
            "# HELP agente_dp_memory_percent Uso de memória em porcentagem",
            "# TYPE agente_dp_memory_percent gauge",
            f"agente_dp_memory_percent {metrics['system']['memory_percent']}",
            "",
            "# HELP agente_dp_uptime_seconds Tempo de atividade em segundos",
            "# TYPE agente_dp_uptime_seconds counter",
            f"agente_dp_uptime_seconds {metrics['info']['uptime_seconds']}",
        ]

        return "\n".join(lines)

    def _format_uptime(self, seconds: float) -> str:
        """Formata uptime para leitura humana"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")

        return " ".join(parts)

    def get_health_status(self) -> Dict[str, Any]:
        """Retorna status de saúde do sistema"""
        metrics = self.get_metrics()

        # Verifica condições de saúde
        is_healthy = True
        issues = []

        # CPU alto
        if metrics["system"]["cpu_percent"] > 90:
            is_healthy = False
            issues.append("CPU usage above 90%")

        # Memória alta
        if metrics["system"]["memory_percent"] > 90:
            is_healthy = False
            issues.append("Memory usage above 90%")

        # Disco cheio
        if metrics["system"]["disk_percent"] > 90:
            is_healthy = False
            issues.append("Disk usage above 90%")

        # Taxa de erro alta
        if metrics["application"]["error_rate_percent"] > 10:
            is_healthy = False
            issues.append(
                f"Error rate above 10% ({metrics['application']['error_rate_percent']}%)"
            )

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "checks": {
                "cpu": metrics["system"]["cpu_percent"] < 90,
                "memory": metrics["system"]["memory_percent"] < 90,
                "disk": metrics["system"]["disk_percent"] < 90,
                "error_rate": metrics["application"]["error_rate_percent"] < 10,
            },
            "issues": issues,
            "timestamp": datetime.now().isoformat(),
        }


# Singleton global
_metrics_collector = None


def get_metrics_collector() -> MetricsCollector:
    """Retorna instância singleton do MetricsCollector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Decorator para medir tempo de execução
def monitor_execution_time(func):
    """Decorator para monitorar tempo de execução de funções"""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        collector = get_metrics_collector()
        start_time = time.time()

        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            collector.record_request(success=True, response_time=elapsed)
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            collector.record_request(success=False, response_time=elapsed)
            collector.record_error(type(e).__name__, str(e))
            raise

    return wrapper


if __name__ == "__main__":
    # Teste
    collector = get_metrics_collector()

    # Simula algumas requisições
    import random

    for _ in range(100):
        success = random.random() > 0.1  # 90% sucesso
        response_time = random.uniform(0.1, 2.0)
        collector.record_request(success, response_time)

    collector.record_document_generated("rescisao")
    collector.record_calculation("inss")

    # Mostra métricas
    print(json.dumps(collector.get_metrics(), indent=2))
    print("\n" + "=" * 50)
    print("Prometheus Format:")
    print("=" * 50)
    print(collector.get_prometheus_metrics())
    print("\n" + "=" * 50)
    print("Health Status:")
    print("=" * 50)
    print(json.dumps(collector.get_health_status(), indent=2))
