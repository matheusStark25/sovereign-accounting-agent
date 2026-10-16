"""FGTS: depósito mensal e multa rescisória.

* Empregado: 8% da remuneração (Lei 8.036/1990, art. 15).
* Aprendiz: 2% (art. 15, §7º).
* Empregado doméstico: 8% + 3,2% de indenização compensatória (LC 150/2015, arts. 21 e 22).
* Multa: 40% na dispensa sem justa causa (art. 18, §1º) e 20% no acordo (CLT 484-A).
  A base da multa é o saldo da conta mais o depósito da rescisão.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from .errors import DadosInvalidos
from .money import ZERO, D, nao_negativo, q2

ALIQUOTA_FGTS = Decimal("0.08")
ALIQUOTAS_MENSAIS = {
    "empregado": ALIQUOTA_FGTS,
    "aprendiz": Decimal("0.02"),
    "domestico": Decimal("0.112"),
}
ALIQUOTA_MULTA = {"sem_justa_causa": Decimal("0.40"), "acordo": Decimal("0.20")}


@dataclass(frozen=True)
class ResultadoFgts:
    categoria: str
    base: Decimal
    aliquota: Decimal
    valor: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "categoria": self.categoria,
            "base": float(q2(self.base)),
            "aliquota": float(self.aliquota),
            "fgts": float(self.valor),
        }


def calcular_fgts_mensal(remuneracao, categoria: str = "empregado") -> ResultadoFgts:
    """Depósito mensal do FGTS sobre a remuneração do mês (já com adicionais e horas extras)."""
    nome = str(categoria).strip().lower()
    aliquota = ALIQUOTAS_MENSAIS.get(nome)
    if aliquota is None:
        raise DadosInvalidos(
            f"Categoria de FGTS desconhecida: {categoria!r}. Use: {', '.join(ALIQUOTAS_MENSAIS)}."
        )
    base = nao_negativo(D(remuneracao, "remuneração"), "remuneração")
    return ResultadoFgts(nome, base, aliquota, q2(base * aliquota))


def calcular_multa_fgts(saldo, tipo_rescisao: str, deposito_rescisorio=ZERO) -> Decimal:
    """Multa rescisória sobre (saldo + depósito da rescisão). Zero fora de dispensa sem justa causa e acordo."""
    aliquota = ALIQUOTA_MULTA.get(tipo_rescisao, ZERO)
    base = nao_negativo(D(saldo, "saldo do FGTS"), "saldo do FGTS") + nao_negativo(
        D(deposito_rescisorio, "depósito rescisório"), "depósito rescisório"
    )
    return q2(base * aliquota)
