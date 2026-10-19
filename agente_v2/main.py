"""API FastAPI do agente: login, chat, cálculos trabalhistas, documentos e saúde.

Subir:  ``uvicorn agente_v2.main:app --host 0.0.0.0 --port 8000``
(precisa de ``JWT_SECRET``; para desenvolvimento local use ``AGENTE_ENV=dev``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from contabil_agente.calc import servico
from contabil_agente.chat import ChatEngine, ChatError, ChatStore, llm_do_ambiente
import hashlib
import hmac as _hmac

from contabil_agente.documentos import gerar_pdf_calculo, hash_do_resultado
from contabil_agente.documentos.validadores import validar_cnpj, validar_cpf
from contabil_agente.lgpd.anonimizacao import PIIAnonymizer
from contabil_agente.rpa import estado as rpa_estado
from contabil_agente.rpa.estado import StatusStore
from contabil_agente.lgpd import FINALIDADES, ConsentimentoStore, PoliticaDeRetencao, ServicoLGPD, TratamentoSemBaseLegal
from contabil_agente.documentos.leitura import TAMANHO_MAXIMO, ArquivoInvalido
from contabil_agente.documentos.tipos import TIPOS as TIPOS_DOCUMENTO
from contabil_agente.pipeline import DocumentDispatcher, HistoricoDocumentos, destinos_do_ambiente, provedores_do_ambiente
from contabil_agente.security.worm_audit import WormAudit
from contabil_agente.security.auth import (
    AuthSettings,
    PAPEIS_VALIDOS,
    AuthError,
    AuthLockedError,
    AuthService,
    Principal,
)
from contabil_agente.security.audit_trail_manager import AuditTrailManager
from contabil_agente.security.rbac_manager import Permission

from contabil_agente.governance_manager import (
    AssinaturaInvalida, DecisaoJaResolvida, DecisaoNaoEncontrada, GovernanceManager, GovernancaError, RegraDasDuasPessoas,
    carregar_limites, carregar_par_de_assinatura,
)
from contabil_agente.middleware.limite_de_uso import LimiteDeUso
from contabil_agente.voz import stt_do_ambiente
from contabil_agente.middleware.observabilidade import instalar_observabilidade
from contabil_agente.middleware.seguranca import aplicar_protecoes
from contabil_agente.resilience.readiness import readiness_check

from .auth import exigir, get_auth, token_da_requisicao, usuario_atual
from .config import settings
from .logging_setup import setup_logging
from .rotas_agentes import instalar_agentes
from .rotas_voz import instalar_voz
from .vault_client import VaultClient, carregar_segredos

logger = logging.getLogger("agente_v2")

LOGINS = Counter("agente_logins_total", "Tentativas de login", ["resultado"])
CALCULOS = Counter("agente_calculos_total", "Cálculos executados", ["tipo", "resultado"])
MENSAGENS = Counter("agente_chat_mensagens_total", "Mensagens de chat processadas")

TAMANHO_MAXIMO_JSON = 1_000_000
WEB_DIR = Path(__file__).resolve().parent / "web"


# ---------------------------------------------------------------------- modelos
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=64)


class PedidoPdf(BaseModel):
    dados: Dict[str, Any]
    contexto: Dict[str, Any] = Field(default_factory=dict)


class PedidoConsentimento(BaseModel):
    finalidade: str = Field(max_length=60)
    concedido: bool
    titular: Optional[str] = Field(default=None, max_length=20)


class PedidoExclusao(BaseModel):
    documento: str = Field(max_length=20)


class PedidoFGTS(BaseModel):
    cpf: str = Field(max_length=20)


class PedidoPGMEI(BaseModel):
    cnpj: str = Field(max_length=20)
    ano: Optional[int] = Field(default=None, ge=2000, le=2100)


class PedidoDecisao(BaseModel):
    tipo: str = Field(max_length=40)
    valor: str = Field(max_length=30)
    descricao: str = Field(default="", max_length=300)
    referencia: str = Field(default="", max_length=120)


class PedidoResolucao(BaseModel):
    comentario: str = Field(default="", max_length=300)


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


def _base_legal(request: Request, codigo: str, tenant: str) -> None:
    try:
        request.app.state.lgpd.exigir_base_legal(codigo, tenant)
    except TratamentoSemBaseLegal as exc:
        raise HTTPException(status_code=403, detail=str(exc))


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
    dispatcher: Optional[DocumentDispatcher] = None,
    lgpd: Optional[ServicoLGPD] = None,
    governanca: Optional[GovernanceManager] = None,
    stt: Any = None,
) -> FastAPI:
    app = FastAPI(title=settings.PROJECT_NAME, docs_url="/docs" if settings.ENV == "dev" else None, redoc_url=None)
    precisa_de_segredos = auth is None or audit is None or engine is None or dispatcher is None
    vault = VaultClient.do_ambiente() if precisa_de_segredos else None
    # Segredos: Vault (se configurado) por cima do ambiente. Vault configurado e fora do ar = a API não sobe.
    segredos = carregar_segredos(vault)
    app.state.vault = vault
    app.state.auth = auth or AuthService(AuthSettings.from_env(segredos))
    app.state.chat_engine = engine or ChatEngine(llm=llm_do_ambiente(segredos))
    app.state.chat_store = store or ChatStore(settings.CHAT_DB_PATH)
    app.state.stt = stt if stt is not None else stt_do_ambiente(segredos)  # voz: Whisper pela Groq quando há GROQ_API_KEY
    app.state.audit = audit or AuditTrailManager(worm=WormAudit.do_ambiente(settings.AUDIT_DIR, segredos))
    if dispatcher is None:
        provedores = provedores_do_ambiente(segredos)
        dispatcher = DocumentDispatcher(
            app.state.audit.worm,
            HistoricoDocumentos(settings.DATA_DIR / "documentos.db"),
            worker_llm=provedores["worker"],
            revisor_llm=provedores["revisor"],
            destinos=destinos_do_ambiente(settings.DATA_DIR / "arquivo", segredos),
        )
    app.state.dispatcher = dispatcher
    app.state.rpa_status = StatusStore(settings.DATA_DIR / "rpa.db")
    bruto_rpa = segredos.get("RPA_PQC_PUBLIC_KEY")
    app.state.rpa_chave_publica = json.loads(bruto_rpa) if bruto_rpa else None
    chave_pii = segredos.get("PII_HASH_KEY") or _hmac.new(app.state.auth.settings.secret.encode(), b"lgpd-pii-hash-v1", hashlib.sha256).hexdigest()
    app.state.governanca = governanca or GovernanceManager(
        settings.DATA_DIR / "governanca.db", app.state.audit.worm,
        carregar_par_de_assinatura(segredos, settings.DATA_DIR), carregar_limites(env=segredos),
    )
    app.state.lgpd = lgpd or ServicoLGPD(
        app.state.audit.worm,
        ConsentimentoStore(settings.DATA_DIR / "lgpd.db", chave_pii),
        PoliticaDeRetencao.carregar(),
        raiz_arquivo=settings.DATA_DIR / "arquivo",
        chat_store=app.state.chat_store,
        historico=getattr(dispatcher, "historico", None),
        status_rpa=app.state.rpa_status,
    )
    app.state.limite_login = LimiteDeUso(maximo=10, janela_segundos=60)
    app.state.limite_chat = LimiteDeUso(maximo=60, janela_segundos=60)
    _bootstrap_admin(app.state.auth)

    aplicar_protecoes(app, TAMANHO_MAXIMO_JSON, settings.ALLOWED_ORIGINS, https=os.environ.get("HTTPS_ONLY", "").lower() in ("1", "true", "yes", "sim"))
    instalar_observabilidade(app)

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
        vault = request.app.state.vault
        pronto = readiness_check({"vault": vault} if vault is not None else {}, disk_threshold=95.0)
        if pronto["status"] != "ready":
            raise HTTPException(status_code=503, detail=f"Indisponível: {pronto['reason']}.")
        return {"status": "ready", "llm": request.app.state.chat_engine._llm is not None, "vault": vault is not None}

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
        _base_legal(request, "assistente_de_chat", usuario.tenant_id)
        usar_ia = request.app.state.lgpd.pode_tratar("envio_a_provedor_de_ia", usuario.tenant_id)
        loja: ChatStore = request.app.state.chat_store
        if dados.session_id:
            estado = loja.carregar(dados.session_id, usuario.user_id, usuario.tenant_id)
            if estado is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")
            sid = dados.session_id
        else:
            sid, estado = loja.nova_sessao(usuario.user_id, usuario.tenant_id), {}
        try:
            resultado = request.app.state.chat_engine.responder(estado, dados.message, usar_llm=usar_ia)
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
        _base_legal(request, "calculo_trabalhista", usuario.tenant_id)
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

    # ------------------------------------------------------------- governança
    def _erro_de_governanca(exc: Exception) -> HTTPException:
        codigos = {DecisaoNaoEncontrada: 404, RegraDasDuasPessoas: 403, DecisaoJaResolvida: 409, AssinaturaInvalida: 409}
        return HTTPException(status_code=codigos.get(type(exc), 422), detail=str(exc) or "Decisão não encontrada.")

    @app.post("/api/v1/governanca/decisoes", status_code=201)
    def registrar_decisao(pedido: PedidoDecisao, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        """Registra e assina uma decisão crítica; acima do limite do tipo ela fica PENDENTE até outra pessoa aprovar."""
        try:
            d = request.app.state.governanca.registrar(usuario.tenant_id, usuario.user_id, pedido.tipo, pedido.valor, pedido.descricao, pedido.referencia)
        except GovernancaError as exc:
            raise _erro_de_governanca(exc)
        return d.to_dict()

    @app.get("/api/v1/governanca/pendentes")
    def decisoes_pendentes(request: Request, usuario: Principal = Depends(exigir(Permission.SIGN_DOCUMENTS))):
        return {"pendentes": [d.to_dict() for d in request.app.state.governanca.pendentes(usuario.tenant_id)]}

    @app.get("/api/v1/governanca/decisoes/{decisao_id}")
    def ver_decisao(decisao_id: str, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        gov = request.app.state.governanca
        try:
            d = gov.obter(decisao_id, usuario.tenant_id)
            return {**d.to_dict(), "assinatura_valida": gov.verificar_assinatura(decisao_id, usuario.tenant_id)}
        except GovernancaError as exc:
            raise _erro_de_governanca(exc)

    @app.post("/api/v1/governanca/decisoes/{decisao_id}/aprovar")
    def aprovar_decisao(decisao_id: str, pedido: PedidoResolucao, request: Request, usuario: Principal = Depends(exigir(Permission.SIGN_DOCUMENTS))):
        try:
            return request.app.state.governanca.aprovar(decisao_id, usuario.tenant_id, usuario.user_id, pedido.comentario).to_dict()
        except GovernancaError as exc:
            raise _erro_de_governanca(exc)

    @app.post("/api/v1/governanca/decisoes/{decisao_id}/rejeitar")
    def rejeitar_decisao(decisao_id: str, pedido: PedidoResolucao, request: Request, usuario: Principal = Depends(exigir(Permission.SIGN_DOCUMENTS))):
        try:
            return request.app.state.governanca.rejeitar(decisao_id, usuario.tenant_id, usuario.user_id, pedido.comentario).to_dict()
        except GovernancaError as exc:
            raise _erro_de_governanca(exc)

    # ------------------------------------------------------------------ LGPD
    @app.get("/api/v1/lgpd/finalidades")
    def finalidades(_: Principal = Depends(usuario_atual)):
        return {"finalidades": [
            {"codigo": f.codigo, "descricao": f.descricao, "base_legal": f.base.value, "dados_sensiveis": f.dados_sensiveis}
            for f in FINALIDADES.values()
        ]}

    @app.post("/api/v1/lgpd/consentimentos", status_code=201)
    def registrar_consentimento(
        pedido: PedidoConsentimento, request: Request, usuario: Principal = Depends(exigir(Permission.WRITE_DATA))
    ):
        if not pedido.titular and not ({"tenant_admin", "super_admin"} & set(usuario.roles)):
            raise HTTPException(status_code=403, detail="Só o administrador do tenant registra consentimento de sistema.")
        try:
            n = request.app.state.lgpd.registrar_consentimento(usuario.tenant_id, pedido.titular, pedido.finalidade, pedido.concedido, usuario.user_id)
        except TratamentoSemBaseLegal as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"id": n, "finalidade": pedido.finalidade, "concedido": pedido.concedido}

    @app.get("/api/v1/lgpd/consentimentos")
    def historico_de_consentimentos(
        request: Request, titular: Optional[str] = None, usuario: Principal = Depends(exigir(Permission.READ_SENSITIVE_DATA))
    ):
        return {"historico": request.app.state.lgpd.consentimentos.historico(usuario.tenant_id, titular)}

    @app.delete("/api/v1/lgpd/titular")
    def excluir_titular(pedido: PedidoExclusao, request: Request, usuario: Principal = Depends(exigir(Permission.DELETE_DATA))):
        """Direito de exclusão (LGPD art. 18, VI). O que a lei manda guardar fica retido e é listado."""
        try:
            return request.app.state.lgpd.excluir_titular(usuario.tenant_id, pedido.documento, usuario.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/v1/lgpd/retencao")
    def politica_de_retencao(request: Request, _: Principal = Depends(usuario_atual)):
        return {"prazos_em_dias": request.app.state.lgpd.politica.para_dict()}

    @app.post("/api/v1/lgpd/retencao/executar")
    def executar_retencao(request: Request, usuario: Principal = Depends(exigir(Permission.DELETE_DATA))):
        return {"removidos": request.app.state.lgpd.executar_retencao(usuario.tenant_id, usuario.user_id)}

    # -------------------------------------------------------------------- RPA
    def enfileirar_extrato(request: Request, usuario: Principal, portal: str, documento: str, ano: Optional[int] = None) -> Dict[str, Any]:
        """Enfileira o extrato do FGTS (CPF) ou do PGMEI (CNPJ). O documento vai cifrado (pós-quântico) pelo broker; o robô
        pausa para uma pessoa resolver captcha/login na janela do navegador do worker."""
        pgmei = portal == "pgmei"
        if not (validar_cnpj(documento) if pgmei else validar_cpf(documento)):
            raise HTTPException(status_code=422, detail="CNPJ inválido." if pgmei else "CPF inválido.")
        finalidade = "consulta_extrato_pgmei" if pgmei else "consulta_extrato_fgts"
        try:
            request.app.state.lgpd.exigir_base_legal(finalidade, usuario.tenant_id, documento)
        except TratamentoSemBaseLegal as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        chave = request.app.state.rpa_chave_publica
        if chave is None:
            raise HTTPException(status_code=503, detail="RPA não configurado: falta RPA_PQC_PUBLIC_KEY (gere com: python -m agente_v2.cli gerar-chaves-rpa).")
        from contabil_agente.tarefas.rpa import envelope_do_cpf, extrato_fgts, extrato_pgmei

        titular = PIIAnonymizer.hash_pii(documento, request.app.state.lgpd._chave_hash)
        status_store = request.app.state.rpa_status
        job_id = status_store.criar(usuario.tenant_id, usuario.user_id, "extrato_pgmei" if pgmei else "extrato_fgts", titular)
        envelope = envelope_do_cpf(chave, documento, usuario.tenant_id, job_id, portal)
        _auditar(request, "process_document", usuario, "Extrato do PGMEI solicitado" if pgmei else "Extrato do FGTS solicitado", job=job_id, titular=titular)
        try:
            if pgmei:
                extrato_pgmei.apply_async(args=[job_id, usuario.tenant_id, usuario.user_id, envelope, ano])
            else:
                extrato_fgts.apply_async(args=[job_id, usuario.tenant_id, usuario.user_id, envelope])
        except Exception as exc:  # noqa: BLE001 - broker (Redis) fora do ar
            status_store.atualizar(job_id, rpa_estado.FALHOU, "Fila indisponível.")
            logger.error("Fila indisponível: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Fila de tarefas indisponível (Redis).")
        return {"job_id": job_id, "estado": status_store.obter(job_id, usuario.tenant_id)["estado"]}

    @app.post("/api/v1/rpa/fgts", status_code=202)
    def enfileirar_extrato_fgts(pedido: PedidoFGTS, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        """Extrato do FGTS (CPF), com a pessoa resolvendo só o captcha/login."""
        return enfileirar_extrato(request, usuario, "fgts", pedido.cpf)

    @app.post("/api/v1/rpa/pgmei", status_code=202)
    def enfileirar_extrato_pgmei(pedido: PedidoPGMEI, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        """Extrato/DAS do MEI no PGMEI (CNPJ), com a pessoa resolvendo só o captcha."""
        return enfileirar_extrato(request, usuario, "pgmei", pedido.cnpj, pedido.ano)

    instalar_agentes(app, _auditar, enfileirar_extrato)
    instalar_voz(app, _auditar, _base_legal)

    @app.get("/api/v1/rpa/jobs/{job_id}")
    def estado_do_job(job_id: str, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        job = request.app.state.rpa_status.obter(job_id, usuario.tenant_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
        return job

    @app.post("/api/v1/documentos/lote", status_code=202)
    async def processar_lote_de_documentos(
        request: Request,
        arquivos: list[UploadFile] = File(...),
        usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL)),
    ):
        """Recebe até 50 arquivos e processa todos em segundo plano (Celery), cada um pelo pipeline de 7 estados."""
        if not 1 <= len(arquivos) <= 50:
            raise HTTPException(status_code=422, detail="Envie de 1 a 50 arquivos por lote.")
        _base_legal(request, "processamento_de_documentos", usuario.tenant_id)
        from contabil_agente.tarefas.documentos import processar_lote

        status_store = request.app.state.rpa_status
        job_id = status_store.criar(usuario.tenant_id, usuario.user_id, "lote_documentos")
        pasta = settings.DATA_DIR / "entrada" / usuario.tenant_id / job_id
        pasta.mkdir(parents=True, exist_ok=True)
        nomes = []
        for i, arq in enumerate(arquivos):
            conteudo = await arq.read(TAMANHO_MAXIMO + 1)
            if len(conteudo) > TAMANHO_MAXIMO:
                raise HTTPException(status_code=413, detail=f"{arq.filename}: arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
            sufixo = os.path.splitext(arq.filename or "")[1].lower()
            sufixo = sufixo if sufixo in (".pdf", ".xml", ".txt", ".csv") else ".bin"
            nome = f"{i:03d}{sufixo}"
            (pasta / nome).write_bytes(conteudo)
            nomes.append(nome)
        _auditar(request, "process_document", usuario, "Lote de documentos enviado", job=job_id, arquivos=len(nomes))
        try:
            processar_lote.apply_async(args=[job_id, usuario.tenant_id, usuario.user_id, str(pasta), nomes])
        except Exception as exc:  # noqa: BLE001
            status_store.atualizar(job_id, rpa_estado.FALHOU, "Fila indisponível.")
            logger.error("Fila indisponível: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Fila de tarefas indisponível (Redis).")
        return {"job_id": job_id, "arquivos": len(nomes)}

    # ------------------------------------------------------------ documentos
    @app.get("/api/v1/documentos/tipos")
    def tipos_de_documento(_: Principal = Depends(usuario_atual)):
        return {"tipos": [{"codigo": t.codigo, "nome": t.nome, "categoria": t.categoria} for t in TIPOS_DOCUMENTO.values()]}

    @app.post("/api/v1/documentos")
    async def processar_documento(
        request: Request,
        arquivo: UploadFile = File(...),
        tipo: Optional[str] = Form(default=None, max_length=40),
        persona: str = Form(default="MARCOS", max_length=20),
        usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL)),
    ):
        _base_legal(request, "processamento_de_documentos", usuario.tenant_id)
        usar_ia = request.app.state.lgpd.pode_tratar("envio_a_provedor_de_ia", usuario.tenant_id)
        dados = await arquivo.read(TAMANHO_MAXIMO + 1)
        if len(dados) > TAMANHO_MAXIMO:
            raise HTTPException(status_code=413, detail=f"Arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
        nome = (arquivo.filename or "documento")[:120]
        try:
            resultado = await run_in_threadpool(
                request.app.state.dispatcher.process,
                conteudo=dados, nome=nome, document_type=tipo, persona=persona,
                tenant=usuario.tenant_id, ator=usuario.user_id, usar_ia=usar_ia,
            )
        except ArquivoInvalido as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        corpo = resultado.to_dict()
        if resultado.falha:
            return JSONResponse(corpo, status_code=422)
        return corpo

    # -------------------------------------------------------------- auditoria
    @app.get("/api/v1/auditoria/verificar")
    def verificar_auditoria(
        request: Request, usuario: Principal = Depends(exigir(Permission.VIEW_AUDIT_LOGS)),
    ):
        """Confere a cadeia HMAC da trilha do próprio tenant (e devolve a âncora para guardar fora do servidor)."""
        worm = request.app.state.audit.worm
        v = worm.verificar(usuario.tenant_id)
        resposta = v.to_dict()
        if v.head_seq:
            resposta["ancora"] = worm.ancora(usuario.tenant_id)
        return resposta

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
