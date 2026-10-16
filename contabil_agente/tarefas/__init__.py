"""Tarefas em segundo plano (Celery + Redis): extrato do FGTS e processamento de documentos em lote.

Configuração por ambiente: ``CELERY_BROKER_URL`` (padrão ``redis://localhost:6379/0``),
``CELERY_RESULT_BACKEND`` (padrão: o broker) e ``CELERY_ALWAYS_EAGER=1`` para executar no próprio processo
(desenvolvimento e testes, sem Redis).

Duas filas, dois workers::

    # documentos em lote (pode ser em contêiner)
    celery -A contabil_agente.tarefas worker -Q documentos --loglevel=info

    # RPA do FGTS: na máquina onde a pessoa vai resolver captcha/login, porque o navegador abre ali
    celery -A contabil_agente.tarefas worker -Q rpa --pool=solo --loglevel=info
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
        task_default_queue="documentos",
        task_routes={"rpa.*": {"queue": "rpa"}, "documentos.*": {"queue": "documentos"}},
        include=["contabil_agente.tarefas.rpa", "contabil_agente.tarefas.documentos"],
    )
    return app


celery_app = criar_app()

__all__ = ["celery_app", "criar_app"]
