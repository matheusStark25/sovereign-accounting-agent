"""
Celery Worker - Configuração de Jobs Assíncronos
Arquitetura Sênior com Retry, Auditoria e Rastreamento de Estado

Funcionalidades:
- Jobs assíncronos com Celery
- Políticas de retry automática (3 tentativas)
- Integração com GerenciadorEvidencias
- Rastreamento de estado no Redis
- Callbacks de sucesso e falha
"""

import logging
import os
from datetime import datetime
from typing import Any

from celery import Celery, Task
from celery.signals import task_failure, task_postrun, task_prerun

logger = logging.getLogger(__name__)

# Configuração do Celery
# Default para localhost (desenvolvimento) - em Docker usar REDIS_URL=redis://agente_contabil_redis:6379/0
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# Criação da aplicação Celery
celery_app = Celery(
    "contabil_agente",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
)

# Configurações do Celery
celery_app.conf.update(
    # Serialização
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    # Retry e Timeout
    task_acks_late=True,  # Só confirma após processamento completo
    task_reject_on_worker_lost=True,  # Rejeita se worker cair
    task_time_limit=3600,  # 1 hora máxima por task
    task_soft_time_limit=3300,  # Warning aos 55min
    # Resultados
    result_expires=86400,  # Resultados expiram em 24h
    result_persistent=True,  # Persiste resultados no Redis
    # Workers
    worker_prefetch_multiplier=1,  # Processa 1 tarefa por vez
    worker_max_tasks_per_child=1000,  # Recicla worker após 1000 tasks
    # Rotas de tasks
    task_routes={
        "infra.tasks.*": {"queue": "default"},
        "infra.tasks.folha_*": {"queue": "folha"},
        "infra.tasks.sped_*": {"queue": "sped"},
        "infra.tasks.vencimentos_*": {"queue": "vencimentos"},
    },
    # Agendamento
    beat_schedule={},  # Será preenchido pelo workflow_manager
)


class AuditedTask(Task):
    """
    Task customizada com auditoria automática
    Registra início, fim e erros no GerenciadorEvidencias
    """

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """Callback executado após sucesso da task"""
        try:
            from services.evidence_service import GerenciadorEvidencias

            gerenciador = GerenciadorEvidencias()
            gerenciador.registrar_evidencia(
                tipo=f"job_success_{self.name}",
                descricao=f"Job {self.name} concluído com sucesso",
                dados={
                    "task_id": task_id,
                    "task_name": self.name,
                    "args": str(args),
                    "kwargs": str(kwargs),
                    "result": str(retval)[:1000],  # Limita tamanho
                    "timestamp": datetime.now().isoformat(),
                },
            )
            logger.info(f"✅ Job {task_id} concluído: {self.name}")
        except Exception as e:
            logger.error(f"Erro ao registrar evidência de sucesso: {e}")

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """Callback executado após falha da task"""
        try:
            from services.evidence_service import GerenciadorEvidencias

            gerenciador = GerenciadorEvidencias()
            gerenciador.registrar_evidencia(
                tipo=f"job_failure_{self.name}",
                descricao=f"Job {self.name} falhou",
                dados={
                    "task_id": task_id,
                    "task_name": self.name,
                    "args": str(args),
                    "kwargs": str(kwargs),
                    "error": str(exc),
                    "traceback": str(einfo),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            logger.error(f"❌ Job {task_id} falhou: {self.name} - {exc}")
        except Exception as e:
            logger.error(f"Erro ao registrar evidência de falha: {e}")

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """Callback executado em tentativas de retry"""
        logger.warning(
            f"🔄 Job {task_id} retry: {self.name} - Tentativa {self.request.retries + 1}"
        )


# Define a classe base padrão para todas as tasks
celery_app.Task = AuditedTask


# Signals globais para rastreamento de estado
@task_prerun.connect
def task_prerun_handler(task_id: str, task: Task, *args, **kwargs) -> None:
    """Executado antes de cada task iniciar"""
    logger.info(f"▶️  Iniciando job {task_id}: {task.name}")

    # Atualiza estado no Redis
    try:
        from infra.job_state import JobStateManager

        state_manager = JobStateManager()
        state_manager.update_state(
            task_id,
            status="PROCESSING",
            metadata={"started_at": datetime.now().isoformat()},
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar estado pré-execução: {e}")


@task_postrun.connect
def task_postrun_handler(task_id: str, task: Task, *args, **kwargs) -> None:
    """Executado após cada task concluir (sucesso ou falha)"""
    logger.info(f"⏹️  Finalizando job {task_id}: {task.name}")

    # Atualiza estado final no Redis
    try:
        from infra.job_state import JobStateManager

        state_manager = JobStateManager()

        # Verifica se foi sucesso ou falha
        result = kwargs.get("retval")
        state = kwargs.get("state", "SUCCESS")

        state_manager.update_state(
            task_id,
            status=state,
            metadata={
                "finished_at": datetime.now().isoformat(),
                "result_summary": str(result)[:500] if result else None,
            },
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar estado pós-execução: {e}")


@task_failure.connect
def task_failure_handler(task_id: str, exception: Exception, *args, **kwargs) -> None:
    """Executado quando uma task falha definitivamente"""
    logger.error(f"💀 Job {task_id} falhou definitivamente: {exception}")

    # Atualiza estado de falha no Redis
    try:
        from infra.job_state import JobStateManager

        state_manager = JobStateManager()
        state_manager.update_state(
            task_id,
            status="FAILED",
            metadata={
                "failed_at": datetime.now().isoformat(),
                "error": str(exception),
            },
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar estado de falha: {e}")


# Autodiscover tasks
celery_app.autodiscover_tasks(["infra.tasks"])


if __name__ == "__main__":
    # Inicia o worker
    celery_app.start()
