"""Canal de voz: ``/ws/voz`` (WebSocket). O áudio sobe em pedaços, o Whisper transcreve e a resposta do chat volta frase por frase.

Protocolo (quadros JSON em texto; o áudio vai em quadros binários):

* ``{"tipo": "autenticar", "token": "<JWT>"}`` primeiro (o token não vai na URL): resposta ``{"tipo": "pronto", ...}``;
* ``{"tipo": "inicio", "formato": "webm", "idioma": "pt", "sessao": "<opcional>"}``, quadros binários, ``{"tipo": "fim"}``;
* ``{"tipo": "texto", "texto": "..."}`` pula a transcrição (pergunta digitada, resposta falada);
* ``{"tipo": "cancelar"}`` descarta o áudio acumulado.

Do servidor: ``transcricao``, ``fala`` (uma por frase, na ordem, para o navegador ir falando), ``fim_resposta`` (texto inteiro,
sessão, origem, persona e tom) e ``erro`` (com ``codigo``). A fala sai pelo navegador (Web Speech API), então não há áudio de volta.
Voz exige o consentimento ``envio_a_provedor_de_ia`` (o áudio vai a um terceiro) e a mesma permissão do chat.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, WebSocket
from prometheus_client import Counter

from contabil_agente.chat import ChatError
from contabil_agente.security.auth import AuthError, Principal
from contabil_agente.security.rbac_manager import Permission, SecurityError
from contabil_agente.voz.stt import TAMANHO_MAXIMO_AUDIO, TIPOS_DE_AUDIO, STTIndisponivel

VOZ = Counter("agente_voz_mensagens_total", "Mensagens do canal de voz", ["resultado"])
TEMPO_PARA_AUTENTICAR_S = 10
TEMPO_OCIOSO_S = 300
MAX_TEXTO = 4000
_FRASES = re.compile(r"(?<=[.!?;:])\s+|\n+")


def dividir_em_frases(texto: str) -> List[str]:
    """Quebra a resposta em frases (e linhas) para o navegador ir falando enquanto o resto chega."""
    return [f.strip() for f in _FRASES.split(texto or "") if f and f.strip()]


async def _erro(ws: WebSocket, codigo: str, mensagem: str) -> None:
    VOZ.labels(codigo).inc()
    await ws.send_json({"tipo": "erro", "codigo": codigo, "mensagem": mensagem})


def instalar_voz(app, auditar: Callable[..., Optional[str]], base_legal: Callable[..., Any]) -> None:
    @app.websocket("/ws/voz")
    async def voz(ws: WebSocket) -> None:
        await ws.accept()
        principal = await _autenticar(ws)
        if principal is None:
            return
        estado: Dict[str, Any] = {"buffer": bytearray(), "gravando": False, "formato": "webm", "idioma": "pt", "sessao": None}
        await ws.send_json({"tipo": "pronto", "stt": ws.app.state.stt is not None, "persona": ws.app.state.chat_engine._persona})
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), TEMPO_OCIOSO_S)
            except asyncio.TimeoutError:
                await ws.close(code=1000)
                return
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                if not estado["gravando"]:
                    await _erro(ws, "sem_inicio", 'Envie {"tipo": "inicio"} antes de mandar áudio.')
                    continue
                estado["buffer"].extend(msg["bytes"])
                if len(estado["buffer"]) > TAMANHO_MAXIMO_AUDIO:
                    estado["buffer"].clear()
                    estado["gravando"] = False
                    await _erro(ws, "audio_grande", f"A fala passou de {TAMANHO_MAXIMO_AUDIO // (1024 * 1024)} MB e foi descartada.")
                continue
            try:
                dados = json.loads(msg.get("text") or "")
                tipo = dados["tipo"]
            except (ValueError, KeyError, TypeError):
                await _erro(ws, "quadro_invalido", 'Use quadros JSON com o campo "tipo".')
                continue
            if tipo == "inicio":
                formato = str(dados.get("formato", "webm")).lower()
                if formato not in TIPOS_DE_AUDIO:
                    await _erro(ws, "formato_invalido", f"Formato não suportado. Use: {', '.join(TIPOS_DE_AUDIO)}.")
                    continue
                estado.update(buffer=bytearray(), gravando=True, formato=formato, idioma=str(dados.get("idioma", "pt"))[:5], sessao=dados.get("sessao") or estado["sessao"])
            elif tipo == "cancelar":
                estado.update(buffer=bytearray(), gravando=False)
            elif tipo == "fim":
                audio, estado["gravando"] = bytes(estado["buffer"]), False
                estado["buffer"] = bytearray()
                if not audio:
                    await _erro(ws, "audio_vazio", "Nenhum áudio chegou antes do fim.")
                    continue
                await _processar_audio(ws, principal, estado, audio, auditar, base_legal)
            elif tipo == "texto":
                texto = str(dados.get("texto", "")).strip()
                if not texto or len(texto) > MAX_TEXTO:
                    await _erro(ws, "texto_invalido", f"Envie de 1 a {MAX_TEXTO} caracteres.")
                    continue
                estado["sessao"] = dados.get("sessao") or estado["sessao"]
                await _responder(ws, principal, estado, texto, 0, auditar, base_legal)
            else:
                await _erro(ws, "tipo_desconhecido", f"Tipo desconhecido: {tipo!r}.")

    async def _autenticar(ws: WebSocket) -> Optional[Principal]:
        try:
            primeiro = await asyncio.wait_for(ws.receive_json(), TEMPO_PARA_AUTENTICAR_S)
            if primeiro.get("tipo") != "autenticar" or not isinstance(primeiro.get("token"), str):
                raise AuthError('O primeiro quadro precisa ser {"tipo": "autenticar", "token": "..."}.')
            auth = ws.app.state.auth
            principal = auth.verificar_token(primeiro["token"])
            auth.autorizar(principal, Permission.PROCESS_PAYROLL)
            return principal
        except (AuthError, SecurityError, PermissionError) as exc:
            await ws.send_json({"tipo": "erro", "codigo": "nao_autenticado", "mensagem": str(exc) or "Sem permissão."})
        except (asyncio.TimeoutError, ValueError, TypeError, AttributeError, KeyError):
            await ws.send_json({"tipo": "erro", "codigo": "nao_autenticado", "mensagem": "Autenticação ausente ou inválida."})
        VOZ.labels("nao_autenticado").inc()
        await ws.close(code=4401)
        return None

    async def _processar_audio(ws, principal, estado, audio, auditar, base_legal) -> None:
        if not ws.app.state.lgpd.pode_tratar("envio_a_provedor_de_ia", principal.tenant_id):
            await _erro(ws, "sem_consentimento", "A voz envia o áudio a um provedor externo e exige o consentimento da empresa para IA externa (LGPD).")
            return
        stt = ws.app.state.stt
        if stt is None:
            await _erro(ws, "stt_indisponivel", "A transcrição de voz não está configurada (falta GROQ_API_KEY).")
            return
        try:
            texto = await asyncio.to_thread(stt.transcrever, audio, f"fala.{estado['formato']}", estado["idioma"])
        except STTIndisponivel as exc:
            await _erro(ws, "stt_falhou", str(exc))
            return
        if not texto:
            await _erro(ws, "nao_entendi", "Não consegui entender a fala. Tente de novo, mais perto do microfone.")
            return
        await ws.send_json({"tipo": "transcricao", "texto": texto})
        await _responder(ws, principal, estado, texto, len(audio), auditar, base_legal)

    async def _responder(ws, principal, estado, texto, bytes_de_audio, auditar, base_legal) -> None:
        app_ = ws.app
        if not app_.state.limite_chat.permitir(principal.user_id):
            await _erro(ws, "muitas_mensagens", "Muitas mensagens. Aguarde um momento.")
            return
        try:
            base_legal(ws, "assistente_de_chat", principal.tenant_id)
        except HTTPException as exc:
            await _erro(ws, "sem_base_legal", str(exc.detail))
            return
        loja = app_.state.chat_store
        usar_ia = app_.state.lgpd.pode_tratar("envio_a_provedor_de_ia", principal.tenant_id)
        sid = estado["sessao"]
        conversa = loja.carregar(sid, principal.user_id, principal.tenant_id) if sid else None
        if conversa is None:
            sid, conversa = loja.nova_sessao(principal.user_id, principal.tenant_id), {}
        estado["sessao"] = sid
        try:
            resultado = await asyncio.to_thread(app_.state.chat_engine.responder, conversa, texto, usar_ia)
        except ChatError as exc:
            await _erro(ws, "mensagem_invalida", str(exc))
            return
        loja.salvar(sid, principal.user_id, principal.tenant_id, conversa)
        try:
            auditar(ws, "read", principal, "Mensagem de voz" if bytes_de_audio else "Mensagem de texto no canal de voz", sessao=sid,
                    bytes_de_audio=bytes_de_audio, tamanho=len(texto))
        except HTTPException as exc:
            await _erro(ws, "auditoria_indisponivel", str(exc.detail))
            return
        resposta = resultado["resposta"]
        for n, frase in enumerate(dividir_em_frases(resposta), 1):
            await ws.send_json({"tipo": "fala", "n": n, "texto": frase})
        await ws.send_json({
            "tipo": "fim_resposta", "sessao": sid, "texto": resposta, "status": resultado.get("status", "ok"), "origem": resultado.get("origem"),
            "persona": resultado.get("persona"), "tom": resultado.get("tom"), "tipo_calculo": resultado.get("tipo"),
            "dados_calculados": resultado.get("dados_calculados"),
        })
        VOZ.labels("ok" if bytes_de_audio else "ok_texto").inc()
