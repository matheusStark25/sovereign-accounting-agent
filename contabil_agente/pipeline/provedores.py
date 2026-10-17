"""Provedores de LLM do pipeline: DeepSeek (worker) e Gemini (revisor), por HTTP.

* Só são criados se a chave existir no ambiente (``DEEPSEEK_API_KEY`` e ``GEMINI_API_KEY``). Sem chave o
  pipeline roda em modo determinístico e diz isso no resultado.
* O texto enviado já sai com CPF, CNPJ, e-mail, telefone e cartão mascarados.
* Cada chamada passa por disjuntor, timeout e retry com backoff (``contabil_agente.resilience``).
* A resposta tem de ser JSON; qualquer outra coisa vira ``ProvedorIndisponivel``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Mapping, Optional

import httpx

from contabil_agente.lgpd.anonimizacao import PIIAnonymizer
from contabil_agente.resilience import ChamadaResiliente

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com"
GEMINI_URL = "https://generativelanguage.googleapis.com"
# Nomes conferidos na documentação oficial em 2026-10-17 (os anteriores, deepseek-chat e gemini-2.0-flash, saíram do ar
# ou foram renomeados). Sobrescreva por DEEPSEEK_MODEL / GEMINI_MODEL e confira com: python -m agente_v2.cli verificar-ia
MODELO_DEEPSEEK = "deepseek-flash"
MODELO_GEMINI = "gemini-3.8-flash"
LIMITE_CARACTERES = 24000


class ProvedorIndisponivel(RuntimeError):
    """O provedor não respondeu de forma utilizável (chave, rede, limite, JSON inválido)."""


def mascarar(texto: str) -> str:
    return PIIAnonymizer.anonymize_text(texto)[:LIMITE_CARACTERES]


def extrair_json(texto: str) -> Dict[str, Any]:
    """Primeiro objeto JSON do texto (modelos às vezes embrulham em ```json)."""
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE)
    try:
        dado = json.loads(limpo)
    except ValueError:
        achado = re.search(r"\{.*\}", limpo, re.DOTALL)
        if not achado:
            raise ProvedorIndisponivel("A resposta do modelo não é JSON.")
        try:
            dado = json.loads(achado.group(0))
        except ValueError as exc:
            raise ProvedorIndisponivel("A resposta do modelo não é JSON válido.") from exc
    if not isinstance(dado, dict):
        raise ProvedorIndisponivel("A resposta do modelo não é um objeto JSON.")
    return dado


class _Base:
    nome = "provedor"

    def __init__(self, api_key: str, modelo: str, base_url: str, cliente: Optional[httpx.Client] = None, resiliencia: Optional[ChamadaResiliente] = None):
        if not api_key:
            raise ProvedorIndisponivel(f"{self.nome}: chave de API não configurada.")
        self._chave, self.modelo, self._base = api_key, modelo, base_url.rstrip("/")
        self._http = cliente or httpx.Client(timeout=30.0)
        self._res = resiliencia or ChamadaResiliente(self.nome, limite_falhas=5, janela_reset=60.0, timeout=45.0, tentativas=3, excecoes=(httpx.HTTPError, ProvedorIndisponivel))

    def _enviar(self, sistema: str, usuario: str) -> str:  # pragma: no cover - implementado nas subclasses
        raise NotImplementedError

    def listar_modelos(self) -> list:  # pragma: no cover - implementado nas subclasses
        raise NotImplementedError

    def verificar(self) -> Dict[str, Any]:
        """Confere de verdade com o provedor: a chave vale, o modelo configurado existe e uma chamada mínima volta em JSON."""
        resultado: Dict[str, Any] = {"provedor": self.nome, "modelo": self.modelo, "chave_valida": False, "modelo_existe": False, "chamada_ok": False}
        try:
            modelos = self.listar_modelos()
            resultado["chave_valida"] = True
            resultado["modelo_existe"] = self.modelo in modelos
            if not resultado["modelo_existe"]:
                resultado["erro"] = f"O modelo {self.modelo!r} não está na lista do provedor."
                resultado["alternativas"] = sorted(m for m in modelos if "flash" in m or "chat" in m or "pro" in m)[:12]
                return resultado
            resposta = self.gerar_json('Responda SOMENTE um JSON no formato {"ok": true}.', "Confirme.")
            resultado["chamada_ok"] = isinstance(resposta, dict) and bool(resposta)
        except Exception as exc:  # noqa: BLE001 - o diagnóstico nunca levanta; devolve o motivo
            resultado["erro"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return resultado

    def gerar_json(self, sistema: str, usuario: str) -> Dict[str, Any]:
        """Envia o texto (mascarado) e devolve o JSON da resposta."""
        try:
            bruto = self._res.chamar(self._enviar, sistema, mascarar(usuario))
        except Exception as exc:
            raise ProvedorIndisponivel(f"{self.nome}: {type(exc).__name__}") from exc
        return extrair_json(bruto)


class DeepSeek(_Base):
    nome = "deepseek"

    def __init__(self, api_key: str, modelo: str = MODELO_DEEPSEEK, base_url: str = DEEPSEEK_URL, **kw: Any):
        super().__init__(api_key, modelo, base_url, **kw)

    def _enviar(self, sistema: str, usuario: str) -> str:
        r = self._http.post(
            f"{self._base}/chat/completions",
            headers={"Authorization": f"Bearer {self._chave}"},
            json={
                "model": self.modelo,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                "temperature": 0,
                "max_tokens": 4000,
                "response_format": {"type": "json_object"},
            },
        )
        r.raise_for_status()
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProvedorIndisponivel("deepseek: resposta fora do formato esperado.") from exc

    def listar_modelos(self) -> list:
        r = self._http.get(f"{self._base}/models", headers={"Authorization": f"Bearer {self._chave}"})
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]


class Gemini(_Base):
    nome = "gemini"

    def __init__(self, api_key: str, modelo: str = MODELO_GEMINI, base_url: str = GEMINI_URL, **kw: Any):
        super().__init__(api_key, modelo, base_url, **kw)

    def _enviar(self, sistema: str, usuario: str) -> str:
        r = self._http.post(
            f"{self._base}/v1beta/models/{self.modelo}:generateContent",
            headers={"x-goog-api-key": self._chave},
            json={
                "systemInstruction": {"parts": [{"text": sistema}]},
                "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProvedorIndisponivel("gemini: resposta fora do formato esperado.") from exc

    def listar_modelos(self) -> list:
        nomes: list = []
        pagina = ""
        for _ in range(10):  # a lista vem paginada
            r = self._http.get(f"{self._base}/v1beta/models", params={"pageSize": 1000, **({"pageToken": pagina} if pagina else {})},
                               headers={"x-goog-api-key": self._chave})
            r.raise_for_status()
            corpo = r.json()
            nomes += [m["name"].split("/", 1)[-1] for m in corpo.get("models", [])]
            pagina = corpo.get("nextPageToken", "")
            if not pagina:
                break
        return nomes


def provedores_do_ambiente(env: Optional[Mapping[str, str]] = None) -> Dict[str, Optional[_Base]]:
    """``{"worker": DeepSeek|None, "revisor": Gemini|None}`` conforme as chaves configuradas."""
    env = os.environ if env is None else env
    worker = DeepSeek(env["DEEPSEEK_API_KEY"], env.get("DEEPSEEK_MODEL") or MODELO_DEEPSEEK) if env.get("DEEPSEEK_API_KEY") else None
    revisor = Gemini(env["GEMINI_API_KEY"], env.get("GEMINI_MODEL") or MODELO_GEMINI) if env.get("GEMINI_API_KEY") else None
    return {"worker": worker, "revisor": revisor}
