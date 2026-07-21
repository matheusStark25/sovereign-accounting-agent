"""Cálculos contábeis extraídos de agent_contabil.py

Contém utilitários puros: calcular_13_salario, calcular_ferias,
calcular_rescisao e validar_data.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Dict

from contabil_agente.utils import safe_decimal


def calcular_13_salario(salario: float, meses_trabalhados: int) -> Dict[str, object]:
    try:
        meses = min(max(int(meses_trabalhados), 0), 12)
        salario_dec = safe_decimal(salario)
        valor = (salario_dec / Decimal("12")) * safe_decimal(meses)
        return {"valor_bruto": float(valor.quantize(Decimal("0.01"))), "meses": meses}
    except Exception:
        return {"valor_bruto": 0.0, "meses": 0}


def calcular_ferias(
    salario: float,
    dias_ferias: int = 30,
    abono_pecuniario: bool = False,
    dias_abono: int = 0,
) -> Dict[str, object]:
    try:
        salario_dec = safe_decimal(salario)
        dias = max(int(dias_ferias), 0)
        base = (salario_dec / Decimal("30")) * Decimal(str(dias))
        terco = base / Decimal("3")
        abono = (
            (salario_dec / Decimal("30")) * Decimal(str(dias_abono))
            if abono_pecuniario
            else Decimal("0")
        )
        total = (base + terco + abono).quantize(Decimal("0.01"))
        return {
            "total_ferias": float(total),
            "dias_ferias": dias,
            "dias_abono": int(dias_abono) if abono_pecuniario else 0,
            "abono": float(abono.quantize(Decimal("0.01"))) if abono > 0 else 0,
            "terco_constitucional": float(terco.quantize(Decimal("0.01"))),
        }
    except Exception:
        return {
            "total_ferias": 0.0,
            "dias_ferias": dias_ferias,
            "dias_abono": 0,
            "abono": 0,
            "terco_constitucional": 0.0,
        }


def calcular_rescisao(
    salario: float,
    meses_trabalhados: int,
    tipo: str = "sem_justa_causa",
    saldo_fgts: float = 0.0,
) -> Dict[str, object]:
    try:
        salario_dec = safe_decimal(salario)
        meses = max(int(meses_trabalhados), 0)

        aviso = salario_dec if tipo == "sem_justa_causa" else Decimal("0")

        ferias_base = (salario_dec / Decimal("12")) * Decimal(str(min(meses, 12)))
        ferias_prop = (ferias_base + (ferias_base / Decimal("3"))).quantize(
            Decimal("0.01")
        )

        decimo = (salario_dec / Decimal("12")) * Decimal(str(min(meses, 12)))
        decimo = decimo.quantize(Decimal("0.01"))

        multa = (
            safe_decimal(saldo_fgts) * Decimal("0.40")
            if tipo == "sem_justa_causa"
            else Decimal("0")
        )

        total = (
            aviso + ferias_prop + decimo + Decimal(str(saldo_fgts)) + multa
        ).quantize(Decimal("0.01"))

        return {
            "aviso_previo": float(aviso),
            "ferias_proporcionais": float(ferias_prop),
            "decimo_terceiro": float(decimo),
            "multa_fgts": float(multa.quantize(Decimal("0.01"))),
            "total": float(total),
        }
    except Exception:
        return {
            "aviso_previo": 0,
            "ferias_proporcionais": 0,
            "decimo_terceiro": 0,
            "multa_fgts": 0,
            "total": 0,
        }


def validar_data(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            datetime.strptime(s, fmt)
            return True
        except Exception:
            continue
    return False
