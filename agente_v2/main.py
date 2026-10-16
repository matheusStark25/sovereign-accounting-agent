"""API FastAPI do agente: login, chat, cálculos trabalhistas, documentos e saúde.

Subir:  ``uvicorn agente_v2.main:app --host 0.0.0.0 --port 8000``
(precisa de ``JWT_SECRET``; para desenvolvimento local use ``AGENTE_ENV=dev``).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from contabil_agente.calc import servico
from contabil_agente.chat import ChatEngine, ChatError, ChatStore, llm_do_ambiente
from contabil_agente.documentos import gerar_pdf_calculo, hash_do_resultado
from contabil_agente.security.auth import (
    PAPEIS_VALIDOS,
    AuthError,
    AuthLockedError,
    AuthService,
    Principal,
)
from contabil_agente.security.audit_trail_manager import AuditTrailManager
from contabil_agente.security.rbac_manager import Permission

from .auth import exigir, get_auth, token_da_requisicao, usuario_atual
from .config import settings
from .logging_setup import setup_logging

logger = logging.getLogger("agente_v2")

LOGINS = Counter("agente_logins_total", "Tentativas de login", ["resultado"])
CALCULOS = Counter("agente_calculos_total", "Cálculos executados", ["tipo", "resultado"])
MENSAGENS = Counter("agente_chat_mensagens_total", "Mensagens de chat processadas")

TAMANHO_MAXIMO_JSON = 1_000_000
WEB_DIR = Path(__file__).resolve().parent / "web"


# ---------------------------------------------------------------- limite de uso
class LimiteDeUso:
    """Janela deslizante em memória (por processo). Em vários workers, use também o proxy/WAF."""

    def __init__(self, maximo: int, janela_segundos: int):
        self.maximo, self.janela = maximo, janela_segundos
        self._eventos: Dict[str, Deque[float]] = defaultdict(deque)

    def permitir(self, chave: str) -> bool:
        agora = time.monotonic()
        fila = self._eventos[chave]
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        if len(fila) >= self.maximo:
            return False
        fila.append(agora)
        return True


# ---------------------------------------------------------------------- modelos
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=64)


class PedidoPdf(BaseModel):
    dados: Dict[str, Any]
    contexto: Dict[str, Any] = Field(default_factory=dict)


class NovoUsuario(BaseModel):
    username: str
    password: str
    roles: list[str]
    tenant_id: Optional[str] = None


# ------------------------------------------------------------------- utilidades
AUDIT_FALHAS = Counter("agente_audit_falhas_total", "Falhas ao gravar a trilha de auditoria")


def _auditar(
    request: Request, acao: str, principal: Optional[Principal], descricao: str, sucesso: bool = True,
    obrigatoria: bool = True, **meta,
) -> Optional[str]:
    """Grava na trilha WORM (sem conteúdo de mensagens). Se a trilha falhar, a operação falha com 503."""
    from contabil_agente.security.audit_trail_manager import AuditAction, AuditoriaError

    audit = request.app.state.audit
    try:
        return audit.log(
            tenant_id=principal.tenant_id if principal else "SYSTEM",
            operator_id=principal.user_id if principal else "anonimo",
            action=AuditAction(acao),
            description=descricao,
            success=sucesso,
            metadata=meta,
            ip_address=request.client.host if request.client else None,
        )
    except (AuditoriaError, OSError, ValueError):
        AUDIT_FALHAS.inc()
        logger.critical("Falha ao gravar auditoria (%s)", acao, exc_info=True)
        if obrigatoria:
            raise HTTPException(status_code=503, detail="Trilha de auditoria indisponível: operação não realizada.")
        return None


_CONTEXTO_PERMITIDO = ("empresa", "nome_funcionario", "cpf", "protocolo")


def _resposta_pdf(request: Request, usuario: Principal, tipo: str, resultado: Dict[str, Any], contexto: Dict[str, Any]) -> Response:
    contexto = {k: str(v)[:120] for k, v in contexto.items() if k in _CONTEXTO_PERMITIDO}
    pdf = gerar_pdf_calculo(tipo, resultado, contexto)
    _auditar(request, "process_payroll", usuario, f"PDF de {tipo}", tamanho=len(pdf))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{tipo}.pdf"',
            "X-Calculo-SHA256": hash_do_resultado(resultado),
        },
    )


def _bootstrap_admin(auth: AuthService) -> None:
    """Cria o primeiro administrador a partir do ambiente, só se ainda não houver usuários."""
    usuario = os.environ.get("ADMIN_USERNAME", "").strip()
    senha = os.environ.get("ADMIN_PASSWORD", "")
    if not usuario or not senha or auth.contar_usuarios() > 0:
        return
    auth.criar_usuario(usuario, senha, os.environ.get("ADMIN_TENANT", "default"), ["super_admin"])
    logger.warning("Administrador inicial '%s' criado. Remova ADMIN_PASSWORD do ambiente.", usuario)


# ------------------------------------------------------------------------- app
def create_app(
    auth: Optional[AuthService] = None,
    engine: Optional[ChatEngine] = None,
    store: Optional[ChatStore] = None,
    audit: Any = None,
) -> FastAPI:
    app = FastAPI(title=settings.PROJECT_NAME, docs_url="/docs" if settings.ENV == "dev" else None, redoc_url=None)
    app.state.auth = auth or AuthService()
    app.state.chat_engine = engine or ChatEngine(llm=llm_do_ambiente())
    app.state.chat_store = store or ChatStore(settings.CHAT_DB_PATH)
    app.state.audit = audit or AuditTrailManager(base_directory=str(settings.AUDIT_DIR))
    app.state.limite_login = LimiteDeUso(maximo=10, janela_segundos=60)
    app.state.limite_chat = LimiteDeUso(maximo=60, janela_segundos=60)
    _bootstrap_admin(app.state.auth)

    if settings.ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.ALLOWED_ORIGINS,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        tamanho = request.headers.get("content-length")
        if tamanho and tamanho.isdigit() and int(tamanho) > TAMANHO_MAXIMO_JSON and "multipart" not in request.headers.get(
            "content-type", ""
        ):
            return JSONResponse({"detail": "Corpo da requisição grande demais."}, status_code=413)
        resposta = await call_next(request)
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"
        )
        return resposta

    # ---------------------------------------------------------------- saúde
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        try:
            request.app.state.auth.contar_usuarios()
        except Exception:
            raise HTTPException(status_code=503, detail="Banco de autenticação indisponível.")
        return {"status": "ready", "llm": request.app.state.chat_engine._llm is not None}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ---------------------------------------------------------- autenticação
    @app.post("/token")
    def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), auth: AuthService = Depends(get_auth)):
        ip = request.client.host if request.client else "?"
        if not request.app.state.limite_login.permitir(ip):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
        try:
            principal = auth.autenticar(form.username, form.password)
        except AuthLockedError as exc:
            LOGINS.labels("bloqueado").inc()
            _auditar(request, "access_denied", None, "Login em conta bloqueada", sucesso=False, obrigatoria=False)
            raise HTTPException(status_code=423, detail=str(exc))
        except AuthError as exc:
            LOGINS.labels("falha").inc()
            _auditar(request, "access_denied", None, "Falha de login", sucesso=False, obrigatoria=False)
            raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"})
        LOGINS.labels("ok").inc()
        _auditar(request, "login", principal, "Login realizado")
        return {
            "access_token": auth.emitir_token(principal),
            "token_type": "bearer",
            "expires_in": auth.settings.access_minutes * 60,
        }

    @app.post("/logout", status_code=204)
    def logout(
        request: Request,
        token: str = Depends(token_da_requisicao),
        usuario: Principal = Depends(usuario_atual),
        auth: AuthService = Depends(get_auth),
    ):
        auth.revogar_token(token)
        _auditar(request, "logout", usuario, "Logout realizado")

    @app.get("/users/me")
    def eu(usuario: Principal = Depends(usuario_atual)):
        return usuario.to_dict()

    @app.post("/users", status_code=201)
    def criar_usuario(
        dados: NovoUsuario,
        request: Request,
        admin: Principal = Depends(exigir(Permission.MANAGE_USERS)),
        auth: AuthService = Depends(get_auth),
    ):
        papeis = set(dados.roles)
        if "super_admin" not in admin.roles:
            if "super_admin" in papeis:
                raise HTTPException(status_code=403, detail="Só um super_admin cria outro super_admin.")
            if dados.tenant_id not in (None, admin.tenant_id):
                raise HTTPException(status_code=403, detail="Você só cria usuários do seu próprio tenant.")
        if not papeis <= PAPEIS_VALIDOS:
            raise HTTPException(status_code=422, detail=f"Papéis válidos: {sorted(PAPEIS_VALIDOS)}.")
        try:
            novo = auth.criar_usuario(dados.username, dados.password, dados.tenant_id or admin.tenant_id, sorted(papeis))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _auditar(request, "user_created", admin, "Usuário criado", alvo=novo.user_id)
        return novo.to_dict()

    # ------------------------------------------------------------------ chat
    @app.post("/api/chat")
    def chat(
        dados: ChatRequest,
        request: Request,
        usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL)),
    ):
        if not request.app.state.limite_chat.permitir(usuario.user_id):
            raise HTTPException(status_code=429, detail="Muitas mensagens. Aguarde um momento.")
        loja: ChatStore = request.app.state.chat_store
        if dados.session_id:
            estado = loja.carregar(dados.session_id, usuario.user_id, usuario.tenant_id)
            if estado is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")
            sid = dados.session_id
        else:
            sid, estado = loja.nova_sessao(usuario.user_id, usuario.tenant_id), {}
        try:
            resultado = request.app.state.chat_engine.responder(estado, dados.message)
        except ChatError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        loja.salvar(sid, usuario.user_id, usuario.tenant_id, estado)
        MENSAGENS.inc()
        _auditar(request, "read", usuario, "Mensagem de chat", sessao=sid, tamanho=len(dados.message))
        return {
            "session_id": sid,
            "response": resultado["resposta"],
            "status": resultado.get("status", "ok"),
            "tipo": resultado.get("tipo"),
            "dados_calculados": resultado.get("dados_calculados"),
        }

    @app.get("/api/chat/{session_id}")
    def historico(session_id: str, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        estado = request.app.state.chat_store.carregar(session_id, usuario.user_id, usuario.tenant_id)
        if estado is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")
        return {"session_id": session_id, "mensagens": estado.get("mensagens", [])}

    @app.get("/api/chat/{session_id}/pdf")
    def pdf_da_conversa(
        session_id: str, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))
    ):
        estado = request.app.state.chat_store.carregar(session_id, usuario.user_id, usuario.tenant_id)
        if estado is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")
        ultimo = estado.get("ultimo_calculo")
        if not ultimo:
            raise HTTPException(status_code=404, detail="Esta conversa ainda não tem um cálculo concluído.")
        return _resposta_pdf(request, usuario, ultimo["tipo"], ultimo["resultado"], {"protocolo": session_id})

    # --------------------------------------------------------------- cálculo
    @app.get("/api/v1/calculo/tipos")
    def tipos(_: Principal = Depends(usuario_atual)):
        return {"tipos": list(servico.TIPOS_CALCULO)}

    @app.post("/api/v1/calculo/{tipo}")
    def calcular(
        tipo: str,
        dados: Dict[str, Any],
        request: Request,
        usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL)),
    ):
        if tipo not in servico.TIPOS_CALCULO:
            raise HTTPException(status_code=404, detail=f"Cálculo desconhecido. Use: {', '.join(servico.TIPOS_CALCULO)}.")
        resposta = servico.calcular(tipo, dados)
        CALCULOS.labels(tipo, resposta["status"]).inc()
        _auditar(request, "process_payroll", usuario, f"Cálculo de {tipo}", sucesso=resposta["status"] == "ok")
        if resposta["status"] == "ok":
            return resposta
        codigo = 422
        return JSONResponse(resposta, status_code=codigo)

    @app.post("/api/v1/calculo/{tipo}/pdf")
    def calcular_em_pdf(
        tipo: str,
        pedido: PedidoPdf,
        request: Request,
        usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL)),
    ):
        if tipo not in servico.TIPOS_CALCULO:
            raise HTTPException(status_code=404, detail=f"Cálculo desconhecido. Use: {', '.join(servico.TIPOS_CALCULO)}.")
        resposta = servico.calcular(tipo, pedido.dados)
        CALCULOS.labels(tipo, resposta["status"]).inc()
        if resposta["status"] != "ok":
            return JSONResponse(resposta, status_code=422)
        return _resposta_pdf(request, usuario, tipo, resposta["resultado"], pedido.contexto)

    # ------------------------------------------------------------------- web
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


_app: Optional[FastAPI] = None


def __getattr__(nome: str):
    """``uvicorn agente_v2.main:app`` cria o app na primeira leitura (e falha com mensagem clara sem JWT_SECRET)."""
    global _app
    if nome == "app":
        if _app is None:
            setup_logging()
            _app = create_app()
        return _app
    raise AttributeError(nome)
