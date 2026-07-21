"""
Schemas Pydantic para validação de dados
"""

import warnings
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict

# Suprimir avisos de deprecação da migração Pydantic v1->v2 nos testes
warnings.filterwarnings(
    "ignore", message=".*PydanticDeprecatedSince20.*", category=Warning
)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic.*")


class ChatRequest(BaseModel):
    """Request de chat com validação"""

    mensagem: str = Field(
        ..., min_length=1, max_length=5000, description="Mensagem do usuário"
    )
    session_id: str = Field(
        default_factory=lambda: f"session_{uuid.uuid4().hex[:8]}",
        description="ID da sessão",
    )
    tone: str = Field(
        default="neutro",
        pattern="^(formal|informal|neutro)$",
        description="Tom de resposta",
    )
    intent: Optional[str] = Field(
        None, description="Intenção explícita (rescisao, ferias, etc)"
    )
    conversation_data: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Dados da conversa"
    )

    @field_validator("mensagem")
    def mensagem_nao_vazia(cls, v):
        """Valida que mensagem não é vazia"""
        if not v.strip():
            raise ValueError("Mensagem não pode ser vazia")

        # Bloqueia termos de prompt injection
        termos_bloqueados = [
            "ignore previous",
            "system:",
            "you are chatgpt",
            "###",
            "```",
            "role: system",
            "prompt injection",
            "execute",
            "rm -r",
            "shutdown",
            "format c:",
        ]
        v_lower = v.lower()
        if any(termo in v_lower for termo in termos_bloqueados):
            raise ValueError("Entrada rejeitada por segurança")

        return v.strip()

    model_config = ConfigDict(
        schema_extra={
            "example": {
                "mensagem": "Preciso calcular rescisão para João Silva, salário R$ 3.500",
                "session_id": "session_abc123",
                "tone": "informal",
                "intent": "rescisao",
            }
        }
    )


class ChatResponse(BaseModel):
    """Response padrão do chat"""

    status: str = Field(..., pattern="^(success|error|need_info)$")
    resposta_ia: str
    documentos: List[Dict[str, Any]] = Field(default_factory=list)
    calculo: Optional[Dict[str, Any]] = None
    audio_url: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    requires_auth: Optional[bool] = None
    action_type: Optional[str] = None


class VoiceRequest(BaseModel):
    """Request de voz (usado para validação de form data)"""

    session_id: str = Field(default_factory=lambda: f"session_{uuid.uuid4().hex[:8]}")
    tone: str = Field(default="neutro", pattern="^(formal|informal|neutro)$")
    intent: Optional[str] = None


class LoginRequest(BaseModel):
    """Request de login"""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)

    @field_validator("username")
    def username_valido(cls, v):
        """Valida formato do username"""
        if not re.match(r"^[a-zA-Z0-9_.-]+$", v):
            raise ValueError("Username deve conter apenas letras, números e . _ -")
        return v


class LoginResponse(BaseModel):
    """Response de login"""

    status: str
    access_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    message: Optional[str] = None


class DocumentRequest(BaseModel):
    """Request para gerar documento"""

    tipo: str = Field(
        ..., description="Tipo do documento (rescisao, holerite, contrato, etc)"
    )
    dados: Dict[str, Any] = Field(..., description="Dados para o documento")
    session_id: str = Field(default_factory=lambda: f"session_{uuid.uuid4().hex[:8]}")

    @field_validator("tipo")
    def tipo_valido(cls, v):
        """Valida tipos permitidos"""
        tipos_validos = [
            "rescisao",
            "holerite",
            "contrato",
            "ferias",
            "decimo_terceiro",
            "transferencia",
            "advertencia",
            "suspensao",
            "carta_referencia",
            "atestado_trabalho",
            "declaracao_vinculo",
        ]
        if v.lower() not in tipos_validos:
            raise ValueError(
                f"Tipo '{v}' não é válido. Tipos permitidos: {', '.join(tipos_validos)}"
            )
        return v.lower()


class CalculoRescisaoRequest(BaseModel):
    """Request específico para cálculo de rescisão"""

    nome: str = Field(..., min_length=3, max_length=200)
    salario: Decimal = Field(..., gt=0, le=50000, description="Salário bruto mensal")
    meses_trabalhados: int = Field(
        ..., ge=0, le=600, description="Total de meses trabalhados"
    )
    tipo_rescisao: str = Field(
        default="sem_justa_causa",
        pattern="^(sem_justa_causa|acordo|pedido_demissao|justa_causa)$",
    )
    dependentes_irrf: int = Field(default=0, ge=0, le=10)
    dias_trabalhados_mes: int = Field(default=15, ge=0, le=31)
    ferias_vencidas: int = Field(default=0, ge=0, le=5)

    @field_validator("salario")
    def salario_valido(cls, v):
        """Valida faixa de salário"""
        if v < Decimal("1518.00"):  # Salário mínimo 2026
            raise ValueError("Salário abaixo do mínimo legal")
        return v

    model_config = ConfigDict(
        schema_extra={
            "example": {
                "nome": "João Silva",
                "salario": 3500.00,
                "meses_trabalhados": 24,
                "tipo_rescisao": "sem_justa_causa",
                "dependentes_ir": 2,
                "dias_trabalhados_mes": 15,
                "ferias_vencidas": 0,
            }
        }
    )


class HealthCheckResponse(BaseModel):
    """Response do health check"""

    status: str = "healthy"
    service: str = "agente-contabil"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    online: bool = True
    port: int = 5000
    message: str = "Sistema Online e Funcionando!"


class ErrorResponse(BaseModel):
    """Response de erro padronizado"""

    status: str = "error"
    message: str
    error_type: Optional[str] = None
    error_details: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
