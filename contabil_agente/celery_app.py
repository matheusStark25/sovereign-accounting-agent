"""Initialize Celery app from Config or environment variables.

Exposes `celery_app` (or None) and `CELERY_CONFIGURED` boolean so
other modules can import and use tasks if Celery is available.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

try:
    from celery import Celery

    CELERY_INSTALLED = True
except Exception:
    Celery = None  # type: ignore
    CELERY_INSTALLED = False

logger = logging.getLogger(__name__)


def _get_broker_url() -> Optional[str]:
    # Prefer Config if available, otherwise env
    try:
        from core.config import Config

        broker = getattr(Config, "CELERY_BROKER_URL", None) or os.environ.get(
            "CELERY_BROKER_URL"
        )
    except Exception:
        broker = os.environ.get("CELERY_BROKER_URL")
    return broker


celery_app = None
CELERY_CONFIGURED = False

if CELERY_INSTALLED:
    broker = _get_broker_url()
    if broker:
        try:
            celery_app = Celery(
                "contabil_agente",
                broker=broker,
                backend=os.environ.get("CELERY_RESULT_BACKEND", broker),
            )
            # default include for autodiscovery
            celery_app.conf.update(task_ignore_result=False)
            CELERY_CONFIGURED = True
        except Exception as e:
            logger.warning("Failed to configure Celery app: %s", e)
            celery_app = None
            CELERY_CONFIGURED = False
