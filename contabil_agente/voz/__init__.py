"""Voz: fala para texto (Whisper) e o canal que liga o microfone ao chat. A fala sai pelo navegador (Web Speech API)."""

from .stt import MODELO_STT, STTIndisponivel, WhisperGroq, silencio_wav, stt_do_ambiente

__all__ = ["MODELO_STT", "STTIndisponivel", "WhisperGroq", "silencio_wav", "stt_do_ambiente"]
