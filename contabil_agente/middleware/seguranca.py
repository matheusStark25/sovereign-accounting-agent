"""Proteções HTTP: cabeçalhos de segurança, limite de tamanho do corpo JSON e CORS restrito."""

from __future__ import annotations

from typing import Sequence

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
CABECALHOS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": CSP,
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def aplicar_protecoes(app: FastAPI, tamanho_maximo_json: int = 1_000_000, origens_permitidas: Sequence[str] = (), https: bool = False) -> None:
    if origens_permitidas:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origens_permitidas),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        tamanho = request.headers.get("content-length")
        if (
            tamanho and tamanho.isdigit() and int(tamanho) > tamanho_maximo_json
            and "multipart" not in request.headers.get("content-type", "")
        ):
            return JSONResponse({"detail": "Corpo da requisição grande demais."}, status_code=413)
        resposta = await call_next(request)
        for nome, valor in CABECALHOS.items():
            resposta.headers[nome] = valor
        if https:
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resposta
