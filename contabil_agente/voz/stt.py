"""Fala para texto com o Whisper (via API da Groq): ``WhisperGroq.transcrever(audio)``.

* O áudio é dado pessoal e vai a um terceiro: quem chama só usa isto depois de checar o consentimento
  ``envio_a_provedor_de_ia`` (a rota do WebSocket faz isso).
* Limites: 10 MB por fala e só os formatos que a API aceita; nada é gravado em disco.
* Cada chamada passa por disjuntor, timeout e retry com backoff, como os demais provedores.
"""

from __future__ import annotations

import io
import os
import wave
from typing import Any, Dict, Mapping, Optional

import httpx

from contabil_agente.resilience import ChamadaResiliente

GROQ_URL = "https://api.groq.com"
MODELO_STT = "whisper-large-v3-turbo"
TAMANHO_MAXIMO_AUDIO = 10 * 1024 * 1024
TIPOS_DE_AUDIO = {
    "webm": "audio/webm", "ogg": "audio/ogg", "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "mp4": "audio/mp4", "flac": "audio/flac",
}


class STTIndisponivel(RuntimeError):
    """A transcrição não foi possível (sem chave, rede, limite do provedor ou áudio recusado)."""


def silencio_wav(segundos: float = 1.0, taxa: int = 16000) -> bytes:
    """WAV mono de 16 bits só com silêncio (serve para testar a chave e o modelo sem precisar de uma fala)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(b"\x00\x00" * int(segundos * taxa))
    return buf.getvalue()


class WhisperGroq:
    nome = "whisper"

    def __init__(self, api_key: str, modelo: str = MODELO_STT, base_url: str = GROQ_URL, cliente: Optional[httpx.Client] = None,
                 resiliencia: Optional[ChamadaResiliente] = None):
        if not api_key:
            raise STTIndisponivel("GROQ_API_KEY não configurada.")
        self._chave, self.modelo, self._base = api_key, modelo, base_url.rstrip("/")
        self._http = cliente or httpx.Client(timeout=60.0)
        self._res = resiliencia or ChamadaResiliente("whisper", limite_falhas=5, janela_reset=60.0, timeout=90.0, tentativas=2,
                                                      excecoes=(httpx.HTTPError, STTIndisponivel))

    def _enviar(self, audio: bytes, nome: str, idioma: str) -> str:
        extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
        r = self._http.post(
            f"{self._base}/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._chave}"},
            files={"file": (nome, audio, TIPOS_DE_AUDIO.get(extensao, "application/octet-stream"))},
            data={"model": self.modelo, "language": idioma, "response_format": "json", "temperature": "0"},
        )
        r.raise_for_status()
        try:
            return str(r.json()["text"]).strip()
        except (KeyError, ValueError) as exc:
            raise STTIndisponivel("whisper: resposta fora do formato esperado.") from exc

    def transcrever(self, audio: bytes, nome: str = "fala.webm", idioma: str = "pt") -> str:
        if not audio:
            raise STTIndisponivel("Áudio vazio.")
        if len(audio) > TAMANHO_MAXIMO_AUDIO:
            raise STTIndisponivel(f"Áudio maior que {TAMANHO_MAXIMO_AUDIO // (1024 * 1024)} MB.")
        extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
        if extensao not in TIPOS_DE_AUDIO:
            raise STTIndisponivel(f"Formato de áudio não suportado: {extensao or 'sem extensão'}. Use: {', '.join(TIPOS_DE_AUDIO)}.")
        try:
            return self._res.chamar(self._enviar, audio, nome, idioma)
        except STTIndisponivel:
            raise
        except Exception as exc:
            raise STTIndisponivel(f"whisper: {type(exc).__name__}") from exc

    def listar_modelos(self) -> list:
        r = self._http.get(f"{self._base}/openai/v1/models", headers={"Authorization": f"Bearer {self._chave}"})
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def verificar(self) -> Dict[str, Any]:
        """Confere de verdade: chave válida, modelo existente e uma transcrição (de um silêncio) que volta sem erro."""
        res: Dict[str, Any] = {"provedor": "whisper", "modelo": self.modelo, "chave_valida": False, "modelo_existe": False, "chamada_ok": False}
        try:
            modelos = self.listar_modelos()
            res["chave_valida"] = True
            res["modelo_existe"] = self.modelo in modelos
            if not res["modelo_existe"]:
                res["erro"] = f"O modelo {self.modelo!r} não está na lista da Groq."
                res["alternativas"] = sorted(m for m in modelos if "whisper" in m)
                return res
            self._enviar(silencio_wav(), "silencio.wav", "pt")
            res["chamada_ok"] = True
        except Exception as exc:  # noqa: BLE001 - o diagnóstico nunca levanta; devolve o motivo
            res["erro"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return res


def stt_do_ambiente(env: Optional[Mapping[str, str]] = None) -> Optional[WhisperGroq]:
    """Whisper pela Groq se houver ``GROQ_API_KEY`` (modelo em ``GROQ_STT_MODEL``); sem chave, ``None``: a voz fica desligada."""
    env = os.environ if env is None else env
    chave = (env.get("GROQ_API_KEY") or "").strip()
    return WhisperGroq(chave, (env.get("GROQ_STT_MODEL") or "").strip() or MODELO_STT) if chave else None
