from __future__ import annotations

try:
    import yaml  # type: ignore[reportMissingImports]

    _YAML_AVAILABLE = True
except Exception:
    yaml = None
    _YAML_AVAILABLE = False
from dataclasses import dataclass
from typing import List, Dict, Any
import logging
from datetime import date, datetime

LOGGER = logging.getLogger("intelligence.calculator")


@dataclass
class CalculationStep:
    etapa: str
    periodo_exato: Dict[str, str]
    formula: str
    resultado: float
    fonte_lei_url: str | None = None
    warning: str | None = None


class TaxEngine:
    def __init__(self, rules_path: str = None):
        self.rules_path = rules_path or "rules/tax_rules.yaml"
        try:
            with open(self.rules_path, "r", encoding="utf-8") as fh:
                self.rules = yaml.safe_load(fh)
        except Exception:
            LOGGER.warning(
                "Tax rules not found at %s, using empty rules", self.rules_path
            )
            self.rules = {}

    def _find_rules_for_date(self, dt: date) -> Dict[str, Any]:
        # naive: find first rule where start <= dt <= end
        for k, v in (self.rules or {}).items():
            try:
                start = datetime.fromisoformat(v.get("start")).date()
                end = datetime.fromisoformat(v.get("end")).date()
                if start <= dt <= end:
                    return v
            except Exception:
                continue
        return {}

    def compute_progressive(self, amount: float, as_of: date) -> List[CalculationStep]:
        rule_set = self._find_rules_for_date(as_of)
        bands = rule_set.get("progressive", [])
        steps: List[CalculationStep] = []
        remaining = amount
        total = 0.0
        for band in bands:
            lower = band.get("lower", 0)
            upper = band.get("upper")
            rate = band.get("rate", 0.0)
            applicable = 0.0
            if upper is None:
                applicable = max(0.0, remaining - lower)
            else:
                applicable = max(0.0, min(remaining, upper - lower))
            if applicable <= 0:
                continue
            part = applicable * rate
            steps.append(
                CalculationStep(
                    etapa=f"band_{lower}_{upper}",
                    periodo_exato={"as_of": as_of.isoformat()},
                    formula=f"{applicable} * {rate}",
                    resultado=part,
                    fonte_lei_url=rule_set.get("source"),
                )
            )
            total += part
            remaining -= applicable
            if remaining <= 0:
                break
        return steps

    def calculate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # payload expected to contain amount, date
        amount = float(payload.get("amount", 0.0))
        date_str = payload.get("date")
        as_of = datetime.fromisoformat(date_str).date() if date_str else date.today()

        # Calcular valores trabalhistas brasileiros
        calculos = self.calcular_trabalhista(amount, payload)

        # Também tentar cálculo progressivo se houver regras
        steps = self.compute_progressive(amount, as_of)
        result = sum(s.resultado for s in steps)

        calculos["progressive_total"] = result
        calculos["progressive_steps"] = [s.__dict__ for s in steps]

        return calculos

    def calcular_trabalhista(
        self, salario: float, payload: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Calcula valores trabalhistas brasileiros (INSS, IRRF, Férias, 13º, etc.)"""
        payload = payload or {}

        # Tabela INSS 2024/2025/2026 (valores aproximados)
        inss = self._calcular_inss(salario)

        # Base para IRRF (salário - INSS)
        base_irrf = salario - inss
        irrf = self._calcular_irrf(base_irrf)

        # Salário líquido
        salario_liquido = salario - inss - irrf

        # Férias (salário + 1/3)
        ferias_integral = salario + (salario / 3)

        # 13º proporcional (meses trabalhados)
        meses_trabalhados = int(payload.get("meses_trabalhados", 12))
        decimo_terceiro_proporcional = (salario / 12) * meses_trabalhados

        # FGTS (8% do salário)
        fgts_mensal = salario * 0.08

        # Multa FGTS 40% (para rescisão sem justa causa)
        meses_empresa = int(payload.get("meses_empresa", meses_trabalhados))
        saldo_fgts_estimado = fgts_mensal * meses_empresa
        multa_fgts_40 = saldo_fgts_estimado * 0.40

        return {
            "salario_bruto": round(salario, 2),
            "inss": round(inss, 2),
            "irrf": round(irrf, 2),
            "salario_liquido": round(salario_liquido, 2),
            "ferias_integral": round(ferias_integral, 2),
            "terco_constitucional": round(salario / 3, 2),
            "decimo_terceiro_proporcional": round(decimo_terceiro_proporcional, 2),
            "fgts_mensal": round(fgts_mensal, 2),
            "saldo_fgts_estimado": round(saldo_fgts_estimado, 2),
            "multa_fgts_40": round(multa_fgts_40, 2),
        }

    def _calcular_inss(self, salario: float) -> float:
        """Calcula INSS com alíquotas progressivas 2024/2025/2026"""
        # Faixas INSS 2024 (valores aproximados, válidos até atualização)
        faixas = [
            (1412.00, 0.075),  # Até 1.412,00 - 7,5%
            (2666.68, 0.09),  # De 1.412,01 até 2.666,68 - 9%
            (4000.03, 0.12),  # De 2.666,69 até 4.000,03 - 12%
            (7786.02, 0.14),  # De 4.000,04 até 7.786,02 - 14%
        ]

        teto_inss = 7786.02
        if salario > teto_inss:
            salario_calc = teto_inss
        else:
            salario_calc = salario

        inss_total = 0.0
        anterior = 0.0

        for limite, aliquota in faixas:
            if salario_calc <= anterior:
                break
            base = min(salario_calc, limite) - anterior
            if base > 0:
                inss_total += base * aliquota
            anterior = limite

        return inss_total

    def _calcular_irrf(self, base: float) -> float:
        """Calcula IRRF com alíquotas progressivas 2024/2025/2026"""
        # Faixas IRRF 2024 (valores aproximados)
        # Base de cálculo = Salário - INSS - Dependentes (R$ 189,59 por dependente)

        if base <= 2259.20:
            return 0.0  # Isento
        elif base <= 2826.65:
            return (base * 0.075) - 169.44
        elif base <= 3751.05:
            return (base * 0.15) - 381.44
        elif base <= 4664.68:
            return (base * 0.225) - 662.77
        else:
            return (base * 0.275) - 896.00

    def explain_calculation(self, calc_result: Dict[str, Any]) -> Dict[str, str]:
        """Generate markdown explanation and Mermaid dependency graph for forensic output."""
        steps = calc_result.get("steps", [])
        md_lines = ["# Explicação do Cálculo", ""]
        mermaid_lines = ["graph TD"]
        for i, s in enumerate(steps):
            node = f"step{i}['{s.get('etapa')}']"
            mermaid_lines.append(node)
            md_lines.append(f"## Etapa {i+1}: {s.get('etapa')}")
            md_lines.append(f"- Período: {s.get('periodo_exato')}")
            md_lines.append(f"- Fórmula: `{s.get('formula')}`")
            md_lines.append(f"- Resultado: **{s.get('resultado')}**")
            if s.get("fonte_lei_url"):
                md_lines.append(f"- Fonte: {s.get('fonte_lei_url')}")
            md_lines.append("")
            if i > 0:
                mermaid_lines.append(f"step{i-1} --> step{i}")

        return {"markdown": "\n".join(md_lines), "mermaid": "\n".join(mermaid_lines)}
