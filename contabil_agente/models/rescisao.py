from __future__ import annotations
from enum import Enum
from datetime import date
from pydantic import BaseModel, validator, Field


class MotivoRescisao(str, Enum):
    DEMISSAO = "demissao"
    PEDIDO = "pedido"
    ACORDO = "acordo"
    RESCISAO_CONSENSO = "rescisaoconcenso"


class RescisaoInput(BaseModel):
    """Pydantic model representing a rescisão input record.

    Validations:
    - `salario_base` must be > 0
    - `data_demissao` must be after `data_admissao`
    """

    id: str = Field(..., description="Unique identifier for the record")
    nome: str = Field(..., description="Employee name")
    salario_base: float = Field(..., description="Base salary")
    data_admissao: date = Field(..., description="Admission date")
    data_demissao: date = Field(..., description="Dismissal date")
    motivo: MotivoRescisao = Field(..., description="Reason for termination")

    @validator("salario_base")
    def salario_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("salario_base must be greater than 0")
        return v

    @validator("data_demissao")
    def demissao_after_admissao(cls, v: date, values: dict) -> date:
        adm = values.get("data_admissao")
        if adm and v <= adm:
            raise ValueError("data_demissao must be after data_admissao")
        return v
