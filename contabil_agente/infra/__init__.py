"""
Infraestrutura - Camada de Jobs Assíncronos e Orquestração
"""

from .worker import celery_app

__all__ = ["celery_app"]
