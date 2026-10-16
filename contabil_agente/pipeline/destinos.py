"""Destinos da etapa DISPATCHING: o que acontece com o resultado depois de revisado.

* ``ArquivoDestino``: grava o documento original e o resultado (JSON) em
  ``<raiz>/<tenant>/<tipo>/<sha256>.{ext,json}``, com permissão 0600 e escrita atômica.
* ``WebhookDestino``: envia o resultado por POST assinado (HMAC-SHA256 no cabeçalho
  ``X-Signature``), com retry e disjuntor.
* ``CallbackDestino``: chama uma função Python (integração direta; só pela API Python).

``destinos_do_ambiente`` monta a lista a partir do ambiente: o arquivo sempre; o webhook quando existirem
``DOCUMENTOS_WEBHOOK_URL`` e ``DOCUMENTOS_WEBHOOK_SECRET``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol

import httpx

from contabil_agente.resilience import ChamadaResiliente


class Destino(Protocol):
    nome: str

    def enviar(self, contexto: Dict[str, Any]) -> Dict[str, Any]: ...


class ErroDeDestino(RuntimeError):
    pass


def _escrever_atomico(destino: Path, dados: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = destino.with_suffix(destino.suffix + ".tmp")
    temp.write_bytes(dados)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, destino)


class ArquivoDestino:
    nome = "arquivo"

    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def enviar(self, contexto: Dict[str, Any]) -> Dict[str, Any]:
        tenant, tipo, sha = contexto["tenant"], contexto["tipo"], contexto["sha256"]
        for parte in (tenant, tipo, sha):
            if not parte or any(c in str(parte) for c in "/\\:") or str(parte).startswith("."):
                raise ErroDeDestino(f"Nome de pasta inseguro: {parte!r}")
        pasta = self.raiz / tenant / tipo
        resultado = pasta / f"{sha}.json"
        _escrever_atomico(resultado, json.dumps(contexto["resultado"], ensure_ascii=False, indent=2, default=str).encode("utf-8"))
        caminhos = {"resultado": str(resultado)}
        if contexto.get("bytes") is not None:
            original = pasta / f"{sha}{contexto.get('extensao') or '.bin'}"
            _escrever_atomico(original, contexto["bytes"])
            caminhos["original"] = str(original)
        return caminhos


class WebhookDestino:
    nome = "webhook"

    def __init__(self, url: str, segredo: str, cliente: Optional[httpx.Client] = None, resiliencia: Optional[ChamadaResiliente] = None):
        if not url.startswith("https://") and not url.startswith("http://localhost") and not url.startswith("http://127.0.0.1"):
            raise ErroDeDestino("O webhook precisa usar HTTPS.")
        if len(segredo) < 16:
            raise ErroDeDestino("Segredo do webhook curto demais (mínimo 16 caracteres).")
        self.url, self._segredo = url, segredo.encode("utf-8")
        self._http = cliente or httpx.Client(timeout=15.0)
        self._res = resiliencia or ChamadaResiliente("webhook", limite_falhas=5, janela_reset=60, timeout=20, tentativas=3, excecoes=(httpx.HTTPError,))

    def assinar(self, corpo: bytes) -> str:
        return "sha256=" + hmac.new(self._segredo, corpo, hashlib.sha256).hexdigest()

    def enviar(self, contexto: Dict[str, Any]) -> Dict[str, Any]:
        corpo = json.dumps({"tipo": contexto["tipo"], "sha256": contexto["sha256"], "resultado": contexto["resultado"]}, ensure_ascii=False, default=str).encode("utf-8")

        def post() -> httpx.Response:
            r = self._http.post(self.url, content=corpo, headers={"Content-Type": "application/json", "X-Signature": self.assinar(corpo)})
            r.raise_for_status()
            return r

        try:
            r = self._res.chamar(post)
        except Exception as exc:
            raise ErroDeDestino(f"Webhook falhou: {type(exc).__name__}") from exc
        return {"status_http": r.status_code}


class CallbackDestino:
    nome = "callback"

    def __init__(self, funcao: Callable[[Dict[str, Any]], Any]):
        self._funcao = funcao

    def enviar(self, contexto: Dict[str, Any]) -> Dict[str, Any]:
        self._funcao(contexto)
        return {"ok": True}


def destinos_do_ambiente(raiz_arquivo: str | Path, env: Optional[Dict[str, str]] = None) -> list:
    """Arquivo local sempre; webhook assinado se ``DOCUMENTOS_WEBHOOK_URL`` e ``DOCUMENTOS_WEBHOOK_SECRET`` estiverem definidos.

    O webhook recebe o resultado de todas as empresas desta instalação: aponte só para um serviço do operador."""
    env = os.environ if env is None else env
    destinos: list = [ArquivoDestino(raiz_arquivo)]
    url, segredo = (env.get("DOCUMENTOS_WEBHOOK_URL") or "").strip(), env.get("DOCUMENTOS_WEBHOOK_SECRET") or ""
    if url or segredo:
        destinos.append(WebhookDestino(url, segredo))  # falta um dos dois ou valor inseguro → ErroDeDestino na subida
    return destinos
