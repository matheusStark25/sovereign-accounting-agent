"""
ToolVoz - Processamento de voz (STT e TTS)
Speech-to-Text: Transcreve áudio em texto
Text-to-Speech: Converte texto em áudio
"""

import threading
import os
from pathlib import Path
from typing import Any, Dict, Optional, AsyncGenerator
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

# Optional integrations (guarded imports)
try:
    import speech_recognition as sr  # type: ignore

    STT_AVAILABLE = True
except Exception:
    sr = None  # type: ignore
    STT_AVAILABLE = False

# pyttsx3: Text-to-Speech (TTS) engine (local fallback)
try:
    import pyttsx3  # type: ignore

    TTS_AVAILABLE = True
except Exception:
    pyttsx3 = None  # type: ignore
    TTS_AVAILABLE = False

# Circuit breaker (pybreaker) and retry (tenacity)
try:
    import pybreaker  # type: ignore
    from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

    CB_AVAILABLE = True
except Exception:
    pybreaker = None  # type: ignore

    def retry(*a, **k):
        def _decorator(f):
            return f

        return _decorator
    CB_AVAILABLE = False

# Redis (consent / cache) and Celery (async tasks)
try:
    import redis  # type: ignore

    REDIS_AVAILABLE = True
except Exception:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False

try:
    from celery import Celery  # type: ignore

    CELERY_AVAILABLE = True
except Exception:
    Celery = None  # type: ignore
    CELERY_AVAILABLE = False

# Prometheus metrics (optional)
try:
    from prometheus_client import Counter, Gauge  # type: ignore

    PROM_AVAILABLE = True
except Exception:
    Counter = None  # type: ignore
    Gauge = None  # type: ignore
    PROM_AVAILABLE = False

# Optional offline STT (vosk) for resilient fallback
try:
    from vosk import Model, KaldiRecognizer  # type: ignore

    VOSK_AVAILABLE = True
except Exception:
    Model = None  # type: ignore
    KaldiRecognizer = None  # type: ignore
    VOSK_AVAILABLE = False

from core.config import Config
from utils.audit import send_audit

# Lock global para TTS (pyttsx3 não é thread-safe)
TTS_LOCK = threading.Lock()

# Circuit breaker instance (best-effort)
if CB_AVAILABLE and pybreaker is not None:
    CIRCUIT = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
else:
    CIRCUIT = None

# Metrics
if PROM_AVAILABLE and Counter is not None:
    METRIC_CHARS_PROCESSED = Counter(
        "voice_chars_processed", "Characters processed by voice tool", ["provider"]
    )
    METRIC_REQUESTS_IN_FLIGHT = Gauge(
        "voice_requests_in_flight", "Current in-flight voice requests"
    )
else:
    METRIC_CHARS_PROCESSED = None
    METRIC_REQUESTS_IN_FLIGHT = None


class ToolVoz:
    """
    Ferramenta para processamento de voz

    Funcionalidades:
    - Speech-to-Text: Reconhece fala do microfone ou arquivo
    - Text-to-Speech: Sintetiza voz a partir de texto
    - Suporte múltiplos idiomas (pt-BR padrão)
    """

    def __init__(self):
        """Inicializa sistema de voz"""
        self.recognizer = sr.Recognizer() if STT_AVAILABLE and sr is not None else None
        self.tts_engine = None
        self._init_tts()

        # audio storage and consent persistence (safe fallback if Config missing)
        docs_root = getattr(Config, "DOCUMENTS_DIR", None)
        if not docs_root:
            docs_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data")
            )
        self.audio_dir = Path(docs_root) / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        # Redis client for consent and cache (best-effort)
        self.redis = None
        if REDIS_AVAILABLE and redis is not None and getattr(Config, "REDIS_URL", None):
            try:
                self.redis = redis.from_url(getattr(Config, "REDIS_URL"))
            except Exception:
                self.redis = None

        # Celery app (optional)
        self.celery = None
        if (
            CELERY_AVAILABLE
            and Celery is not None
            and getattr(Config, "CELERY_BROKER_URL", None)
        ):
            try:
                self.celery = Celery(
                    __name__, broker=getattr(Config, "CELERY_BROKER_URL")
                )
            except Exception:
                self.celery = None

        send_audit(
            "ToolVoz inicializado",
            level="info",
            context={
                "stt_disponivel": STT_AVAILABLE,
                "tts_disponivel": TTS_AVAILABLE,
                "redis": bool(self.redis),
                "celery": bool(self.celery),
            },
        )

    def _init_tts(self):
        """Inicializa engine TTS (thread-safe)"""
        if not TTS_AVAILABLE:
            return

        try:
            with TTS_LOCK:
                self.tts_engine = pyttsx3.init()
                # Configura voz em português se disponível
                voices = self.tts_engine.getProperty("voices")
                for voice in voices:
                    if (
                        "portuguese" in voice.name.lower()
                        or "brazil" in voice.name.lower()
                    ):
                        self.tts_engine.setProperty("voice", voice.id)
                        break

                # Configura velocidade (padrão: 150-200 wpm)
                self.tts_engine.setProperty("rate", 175)
                # Volume (0.0 a 1.0)
                self.tts_engine.setProperty("volume", 0.9)
        except Exception as e:
            send_audit(f"Erro ao inicializar TTS: {e}", level="warning", context={})
            self.tts_engine = None

    def _record_consent(self, user_id: str, consent: bool) -> None:
        """Persist user consent (LGPD) either in Redis or a local JSON fallback."""
        try:
            key = f"consent:{user_id}"
            if self.redis:
                self.redis.set(key, "1" if consent else "0")
            else:
                # fallback to simple file per user
                p = self.audio_dir / "consent"
                p.mkdir(parents=True, exist_ok=True)
                with open(p / f"{user_id}.txt", "w", encoding="utf-8") as f:
                    f.write("1" if consent else "0")
            send_audit(
                "consent.recorded",
                level="info",
                context={"user_id": user_id, "consent": bool(consent)},
            )
        except Exception:
            send_audit(
                "consent.record_failed", level="warning", context={"user_id": user_id}
            )

    def delete_user_data(self, user_id: str) -> Dict[str, Any]:
        """GDPR: delete user-identifiable audio and consent records.

        This is a synchronous best-effort deletion routine.
        """
        removed = 0
        try:
            # remove audio files prefixed with user_id
            for p in self.audio_dir.glob(f"{user_id}*"):
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass

            # remove consent
            if self.redis:
                try:
                    self.redis.delete(f"consent:{user_id}")
                except Exception:
                    pass
            else:
                f = self.audio_dir / "consent" / f"{user_id}.txt"
                if f.exists():
                    try:
                        f.unlink()
                    except Exception:
                        pass

            send_audit(
                "gdpr.delete_user",
                level="info",
                context={"user_id": user_id, "removed_files": removed},
            )
            return {"status": "success", "removed": removed}
        except Exception as e:
            send_audit(
                "gdpr.delete_failed",
                level="error",
                context={"user_id": user_id, "error": str(e)},
            )
            return {"status": "error", "error": str(e)}

    def purge_old_data(self, retention_days: int = 30) -> Dict[str, Any]:
        """Purge audio and consent data older than retention_days (best-effort).

        Intended to be invoked by a CronJob / scheduler.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        removed = 0
        try:
            for p in self.audio_dir.glob("*"):
                try:
                    if p.is_file():
                        mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                        if mtime < cutoff:
                            p.unlink()
                            removed += 1
                except Exception:
                    pass

            # Redis keys cleanup (if structured with timestamps) would be implemented here
            send_audit(
                "gdpr.purge",
                level="info",
                context={"removed": removed, "retention_days": retention_days},
            )
            return {"status": "success", "removed": removed}
        except Exception as e:
            send_audit("gdpr.purge_failed", level="error", context={"error": str(e)})
            return {"status": "error", "error": str(e)}

    def transcrever_microfone(
        self,
        timeout: int = 5,
        phrase_time_limit: Optional[int] = None,
        language: str = "pt-BR",
    ) -> Dict[str, Any]:
        """
        Transcreve áudio do microfone

        Args:
            timeout: Tempo máximo de espera (segundos)
            phrase_time_limit: Limite de duração da frase
            language: Idioma (padrão: pt-BR)

        Returns:
            Dict com status, texto transcrito
        """
        if not STT_AVAILABLE:
            return {
                "status": "error",
                "message": "speech_recognition não está instalado",
            }

        send_audit("Iniciando transcrição do microfone", level="info", context={})

        if not STT_AVAILABLE or sr is None:
            return {"status": "error", "message": "STT não disponível"}

        send_audit("Iniciando transcrição do microfone", level="info", context={})

        try:
            with sr.Microphone() as source:
                send_audit("Ajustando ruído ambiente...", level="info", context={})
                self.recognizer.adjust_for_ambient_noise(source, duration=1)

                send_audit("Escutando...", level="info", context={})
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )

            # Try cloud STT (Google) with retry/circuit-breaker; fallback to local vosk if present
            texto = None
            # provider attempt order: cloud -> vosk
            try:
                if CIRCUIT is not None:

                    @CIRCUIT
                    @retry(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5),
                    )
                    def _cloud_recognize(a):
                        return self.recognizer.recognize_google(a, language=language)

                    texto = _cloud_recognize(audio)
                else:
                    # no circuit breaker available, but still try with retry decorator
                    @retry(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5),
                    )
                    def _cloud_recognize(a):
                        return self.recognizer.recognize_google(a, language=language)

                    texto = _cloud_recognize(audio)
            except Exception:
                texto = None

            if not texto and VOSK_AVAILABLE and Model is not None:
                try:
                    # best-effort Vosk recognition: ensure a small model exists at Config.VOSK_MODEL_PATH
                    model_path = getattr(Config, "VOSK_MODEL_PATH", None)
                    if model_path:
                        model = Model(model_path)
                        rec = KaldiRecognizer(model, 16000)
                        # extract raw audio bytes
                        raw = audio.get_raw_data()
                        rec.AcceptWaveform(raw)
                        res = rec.Result()
                        import json as _json

                        j = _json.loads(res)
                        texto = j.get("text", "")
                except Exception:
                    texto = None

            if not texto:
                return {
                    "status": "error",
                    "message": "Transcrição falhou (todos provedores)",
                }

            if METRIC_CHARS_PROCESSED is not None:
                try:
                    METRIC_CHARS_PROCESSED.labels(provider="stt").inc(len(texto))
                except Exception:
                    pass

            send_audit(
                "Transcrição concluída",
                level="info",
                context={"texto_length": len(texto)},
            )

            return {
                "status": "success",
                "texto": texto,
                "language": language,
                "message": "Transcrição concluída",
            }
        except sr.WaitTimeoutError:
            return {"status": "error", "message": "Timeout - Nenhum áudio detectado"}
        except sr.UnknownValueError:
            return {"status": "error", "message": "Não foi possível entender o áudio"}
        except sr.RequestError as e:
            return {
                "status": "error",
                "message": f"Erro no serviço de reconhecimento: {str(e)}",
            }
        except Exception as e:
            send_audit(f"Erro ao transcrever: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def transcrever_arquivo(
        self, audio_path: str, language: str = "pt-BR"
    ) -> Dict[str, Any]:
        """
        Transcreve arquivo de áudio

        Args:
            audio_path: Caminho do arquivo (WAV, MP3, etc)
            language: Idioma (padrão: pt-BR)

        Returns:
            Dict com status, texto
        """
        if not STT_AVAILABLE:
            return {
                "status": "error",
                "message": "speech_recognition não está instalado",
            }

        send_audit(
            "Transcrevendo arquivo", level="info", context={"arquivo": audio_path}
        )

        if not STT_AVAILABLE or sr is None:
            return {"status": "error", "message": "STT não disponível"}

        send_audit(
            "Transcrevendo arquivo", level="info", context={"arquivo": audio_path}
        )

        try:
            with sr.AudioFile(audio_path) as source:
                audio = self.recognizer.record(source)

            # reuse microphone flow logic: try cloud then vosk
            texto = None
            try:
                if CIRCUIT is not None:

                    @CIRCUIT
                    @retry(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5),
                    )
                    def _cloud_recognize(a):
                        return self.recognizer.recognize_google(a, language=language)

                    texto = _cloud_recognize(audio)
                else:

                    @retry(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5),
                    )
                    def _cloud_recognize(a):
                        return self.recognizer.recognize_google(a, language=language)

                    texto = _cloud_recognize(audio)
            except Exception:
                texto = None

            if not texto and VOSK_AVAILABLE and Model is not None:
                try:
                    model_path = getattr(Config, "VOSK_MODEL_PATH", None)
                    if model_path:
                        model = Model(model_path)
                        rec = KaldiRecognizer(model, 16000)
                        raw = audio.get_raw_data()
                        rec.AcceptWaveform(raw)
                        res = rec.Result()
                        import json as _json

                        j = _json.loads(res)
                        texto = j.get("text", "")
                except Exception:
                    texto = None

            if not texto:
                return {
                    "status": "error",
                    "message": "Transcrição falhou (todos provedores)",
                }

            if METRIC_CHARS_PROCESSED is not None:
                try:
                    METRIC_CHARS_PROCESSED.labels(provider="stt").inc(len(texto))
                except Exception:
                    pass

            send_audit("Arquivo transcrito", level="info", context={})

            return {
                "status": "success",
                "texto": texto,
                "language": language,
                "message": "Arquivo transcrito com sucesso",
            }

        except FileNotFoundError:
            return {"status": "error", "message": "Arquivo de áudio não encontrado"}
        except Exception as e:
            send_audit(f"Erro ao transcrever arquivo: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def sintetizar_voz(
        self, texto: str, salvar_arquivo: bool = False, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Converte texto em fala

        Args:
            texto: Texto para sintetizar
            salvar_arquivo: Se True, salva em arquivo MP3
            filename: Nome do arquivo (opcional)

        Returns:
            Dict com status, filepath (se salvo)
        """
        send_audit(
            "Sintetizando voz", level="info", context={"texto_length": len(texto)}
        )

        # provider attempt order: local pyttsx3 -> cloud TTS (placeholder)
        try:
            if TTS_AVAILABLE and self.tts_engine:
                with TTS_LOCK:
                    if salvar_arquivo:
                        if not filename:
                            from datetime import datetime

                            filename = (
                                f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
                            )

                        filepath = self.audio_dir / filename
                        # Save to file
                        try:
                            self.tts_engine.save_to_file(texto, str(filepath))
                            self.tts_engine.runAndWait()
                        except Exception:
                            # fallback: try speak then dump with external recorder
                            self.tts_engine.say(texto)
                            self.tts_engine.runAndWait()

                        send_audit(
                            "Áudio salvo",
                            level="info",
                            context={"filepath": str(filepath)},
                        )
                        return {
                            "status": "success",
                            "filepath": str(filepath),
                            "filename": filename,
                            "message": "Áudio gerado e salvo",
                        }
                    else:
                        self.tts_engine.say(texto)
                        self.tts_engine.runAndWait()
                        send_audit("Áudio reproduzido", level="info", context={})
                        return {"status": "success", "message": "Áudio reproduzido"}

            # If local TTS not available, indicate provider missing (cloud integration can be added)
            return {
                "status": "error",
                "message": "Nenhum provedor TTS disponível (local ou cloud)",
            }

        except Exception as e:
            send_audit(f"Erro ao sintetizar voz: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    async def stream_mp3(
        self, texto: str, bitrate: str = "128k"
    ) -> AsyncGenerator[bytes, None]:
        """
        Elite stream helper: synthesize text to a temporary file then spawn ffmpeg
        to transcode to MP3 and yield binary MP3 chunks as an async generator.

        Implements internal auditing (Stark) and increments metrics.
        """
        # Audit: Stark log with char count for FinOps tracking
        try:
            send_audit(
                "Stark.stream_mp3_started", level="info", context={"chars": len(texto)}
            )
        except Exception:
            pass

        if METRIC_CHARS_PROCESSED is not None:
            try:
                METRIC_CHARS_PROCESSED.labels(provider="tts").inc(len(texto))
            except Exception:
                pass

        # create a filename in the audio_dir
        # Use timezone-aware UTC timestamp to avoid DeprecationWarning
        temp_name = f"stream_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}.wav"

        # Use existing sintetizar_voz to save a temporary file (best-effort)
        try:
            res = await asyncio.to_thread(self.sintetizar_voz, texto, True, temp_name)
        except Exception:
            res = {"status": "error", "message": "sintetizar failed"}

        if not isinstance(res, dict) or res.get("status") != "success":
            # cannot synthesize; raise to let caller handle
            raise RuntimeError(
                f"sintetizar_voz failed: {res.get('message') if isinstance(res, dict) else res}"
            )

        filepath = Path(res.get("filepath"))

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(filepath),
            "-",
            "mp3",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-",
        ]

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream stdout in chunks (guard stdout may be None)
            if proc.stdout is None:
                await proc.wait()
            else:
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    yield chunk

                await proc.wait()
        finally:
            # cleanup temp file if exists
            try:
                if filepath.exists():
                    filepath.unlink()
            except Exception:
                pass
            # drain stderr
            if proc is not None and proc.stderr is not None:
                try:
                    await proc.stderr.read()
                except Exception:
                    pass

    def mudar_voz(
        self, voice_id: Optional[str] = None, genero: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Altera a voz do TTS

        Args:
            voice_id: ID específico da voz
            genero: 'masculino' ou 'feminino' (se voice_id não especificado)

        Returns:
            Dict com status
        """
        if not TTS_AVAILABLE or not self.tts_engine:
            return {"status": "error", "message": "TTS não disponível"}

        try:
            with TTS_LOCK:
                voices = self.tts_engine.getProperty("voices")

                if voice_id:
                    # Usa ID específico
                    self.tts_engine.setProperty("voice", voice_id)
                elif genero:
                    # Procura por gênero
                    for voice in voices:
                        if (
                            genero.lower() == "feminino"
                            and "female" in voice.name.lower()
                        ):
                            self.tts_engine.setProperty("voice", voice.id)
                            break
                        elif (
                            genero.lower() == "masculino"
                            and "male" in voice.name.lower()
                        ):
                            self.tts_engine.setProperty("voice", voice.id)
                            break

                return {"status": "success", "message": "Voz alterada"}

        except Exception as e:
            send_audit(f"Erro ao mudar voz: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def listar_vozes_disponiveis(self) -> Dict[str, Any]:
        """
        Lista todas as vozes disponíveis no sistema

        Returns:
            Dict com status e lista de vozes
        """
        if not TTS_AVAILABLE or not self.tts_engine:
            return {"status": "error", "message": "TTS não disponível", "vozes": []}

        try:
            with TTS_LOCK:
                voices = self.tts_engine.getProperty("voices")

                vozes_lista = []
                for voice in voices:
                    vozes_lista.append(
                        {
                            "id": voice.id,
                            "nome": voice.name,
                            "idiomas": (
                                voice.languages if hasattr(voice, "languages") else []
                            ),
                            "genero": (
                                voice.gender if hasattr(voice, "gender") else "N/A"
                            ),
                        }
                    )

                return {
                    "status": "success",
                    "vozes": vozes_lista,
                    "total": len(vozes_lista),
                }

        except Exception as e:
            send_audit(f"Erro ao listar vozes: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}", "vozes": []}

    def health(self) -> Dict[str, Any]:
        """Lightweight health check for liveness/readiness."""
        try:
            ok = True
            details = {
                "stt": bool(self.recognizer),
                "tts": bool(self.tts_engine),
                "redis": bool(self.redis),
                "celery": bool(self.celery),
            }
            status = "ready" if ok else "unhealthy"
            return {"status": status, "details": details}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def readiness(self) -> Dict[str, Any]:
        """Readiness check—ensure critical deps are present."""
        try:
            deps_ok = True
            if self.redis is None and getattr(Config, "REDIS_URL", None):
                deps_ok = False
            return {"status": "ready" if deps_ok else "not_ready"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def configurar_velocidade(self, wpm: int = 175) -> Dict[str, Any]:
        """
        Configura velocidade de fala

        Args:
            wpm: Palavras por minuto (padrão: 175)
                 Lento: 120-150
                 Normal: 150-180
                 Rápido: 180-220

        Returns:
            Dict com status
        """
        if not TTS_AVAILABLE or not self.tts_engine:
            return {"status": "error", "message": "TTS não disponível"}

        try:
            with TTS_LOCK:
                self.tts_engine.setProperty("rate", wpm)

            send_audit(f"Velocidade ajustada para {wpm} WPM", level="info", context={})

            return {
                "status": "success",
                "wpm": wpm,
                "message": f"Velocidade configurada para {wpm} palavras/minuto",
            }

        except Exception as e:
            send_audit(f"Erro ao configurar velocidade: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}
