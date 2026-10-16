"""Observabilidade: ``X-Request-ID`` em toda resposta, log de acesso sem dados pessoais e métricas Prometheus."""

from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram

logger = logging.getLogger("acesso")
REQUISICOES = Counter("agente_http_requisicoes_total", "Requisições HTTP", ["metodo", "rota", "status"])
LATENCIA = Histogram("agente_http_latencia_segundos", "Latência das requisições", ["metodo", "rota"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def instalar_observabilidade(app: FastAPI) -> None:
    @app.middleware("http")
    async def observar(request: Request, call_next):
        recebido = request.headers.get("x-request-id", "")
        request_id = recebido if _ID_VALIDO.match(recebido) else uuid.uuid4().hex
        request.state.request_id = request_id
        inicio = time.perf_counter()
        status = 500
        try:
            resposta = await call_next(request)
            status = resposta.status_code
            resposta.headers["X-Request-ID"] = request_id
            return resposta
        finally:
            duracao = time.perf_counter() - inicio
            rota = getattr(request.scope.get("route"), "path", "desconhecida")  # molde da rota, não a URL (evita alta cardinalidade e PII)
            REQUISICOES.labels(request.method, rota, str(status)).inc()
            LATENCIA.labels(request.method, rota).observe(duracao)
            logger.info("%s %s %s %.0fms rid=%s", request.method, rota, status, duracao * 1000, request_id)
