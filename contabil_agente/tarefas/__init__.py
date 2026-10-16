"""Tarefas em segundo plano (Celery + Redis): extrato do FGTS e processamento de documentos em lote.

Configuração por ambiente: ``CELERY_BROKER_URL`` (padrão ``redis://localhost:6379/0``),
``CELERY_RESULT_BACKEND`` (padrão: o broker) e ``CELERY_ALWAYS_EAGER=1`` para executar no próprio processo
(desenvolvimento e testes, sem Redis).

Subir o worker (na máquina onde a pessoa vai resolver captcha/login do FGTS, porque o navegador abre ali)::

    celery -A contabil_agente.tarefas worker --loglevel=info --pool=solo
"""

from __future__ import annotations

import os
from typing import Optional

from celery import Celery


def _eager() -> bool:
    return os.environ.get("CELERY_ALWAYS_EAGER", "").lower() in ("1", "true", "yes", "sim")


def criar_app(broker: Optional[str] = None) -> Celery:
    broker = broker or os.environ.get("CELERY_BROKER_URL") or "redis://localhost:6379/0"
    app = Celery("contabil_agente", broker=broker, backend=os.environ.get("CELERY_RESULT_BACKEND", broker))
    app.conf.update(
        task_always_eager=_eager(),
        task_eager_propagates=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=60 * 30,
        broker_connection_retry_on_startup=True,
        include=["contabil_agente.tarefas.rpa", "contabil_agente.tarefas.documentos"],
    )
    return app


celery_app = criar_app()

__all__ = ["celery_app", "criar_app"]
