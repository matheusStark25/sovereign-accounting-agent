"""
Inicialização do pacote models
"""

from .schemas import (
    CalculoRescisaoRequest,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthCheckResponse,
    LoginRequest,
    LoginResponse,
    VoiceRequest,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "VoiceRequest",
    "LoginRequest",
    "LoginResponse",
    "CalculoRescisaoRequest",
    "HealthCheckResponse",
    "ErrorResponse",
]
