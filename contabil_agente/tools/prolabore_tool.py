"""
ToolProLabore - Cálculo de pró-labore para sócios
Calcula INSS sobre pró-labore (11% até teto)
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

from utils.audit import send_audit


class ToolProLabore:
    """
    Ferramenta para cálculo de pró-labore de sócios

    Regras:
    - INSS: 11% sobre pró-labore (contribuinte individual)
    - Teto INSS 2026: R$ 8.157,41
    - IRRF: Tabela progressiva (mesma de CLT)
    - Sem FGTS (sócio não tem vínculo empregatício)
    - Sem 13º, férias (benefícios exclusivos de CLT)
    """

    def __init__(self):
        """Inicializa ferramenta de pró-labore"""
        # Valores 2026
        self.teto_inss_2026 = Decimal("8157.41")
        self.aliquota_inss_socio = Decimal("0.11")  # 11%

        # Tabela IRRF 2026 (mesma do ToolCalculo)
        self.faixas_irrf_2026 = [
            {
                "min": Decimal("0"),
                "max": Decimal("2259.20"),
                "aliquota": Decimal("0"),
                "deducao": Decimal("0"),
            },
            {
                "min": Decimal("2259.21"),
                "max": Decimal("2826.65"),
                "aliquota": Decimal("0.075"),
                "deducao": Decimal("169.44"),
            },
            {
                "min": Decimal("2826.66"),
                "max": Decimal("3751.05"),
                "aliquota": Decimal("0.15"),
                "deducao": Decimal("381.44"),
            },
            {
                "min": Decimal("3751.06"),
                "max": Decimal("4664.68"),
                "aliquota": Decimal("0.225"),
                "deducao": Decimal("662.77"),
            },
            {
                "min": Decimal("4664.69"),
                "max": Decimal("999999999"),
                "aliquota": Decimal("0.275"),
                "deducao": Decimal("896.00"),
            },
        ]

        self.deducao_dependente_irrf = Decimal("189.59")

        send_audit("ToolProLabore inicializado", level="info", context={})

    def calcular_inss_socio(self, prolabore: Any) -> Decimal:
        """
        Calcula INSS sobre pró-labore (11%)

        Args:
            prolabore: Valor do pró-labore

        Returns:
            Valor do INSS
        """
        try:
            valor = Decimal(str(prolabore))

            # Limita ao teto
            base_calculo = min(valor, self.teto_inss_2026)

            # Aplica 11%
            inss = (base_calculo * self.aliquota_inss_socio).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            return inss

        except Exception:
            return Decimal("0")

    def calcular_irrf_socio(
        self, prolabore: Any, dependentes: int = 0
    ) -> Dict[str, Any]:
        """
        Calcula IRRF sobre pró-labore

        Args:
            prolabore: Valor do pró-labore
            dependentes: Número de dependentes

        Returns:
            Dict com valor IRRF e detalhes
        """
        try:
            valor = Decimal(str(prolabore))

            # Calcula INSS
            inss = self.calcular_inss_socio(valor)

            # Base de cálculo IRRF
            base_irrf = valor - inss - (self.deducao_dependente_irrf * dependentes)

            if base_irrf <= 0:
                return {
                    "irr": Decimal("0"),
                    "base_calculo": base_irrf,
                    "aliquota": "0%",
                    "faixa": "Isento",
                }

            # Encontra faixa
            for faixa in self.faixas_irrf_2026:
                if faixa["min"] <= base_irrf <= faixa["max"]:
                    irrf = (base_irrf * faixa["aliquota"] - faixa["deducao"]).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    irrf = max(Decimal("0"), irrf)

                    return {
                        "irr": irrf,
                        "base_calculo": base_irrf,
                        "aliquota": f"{faixa['aliquota'] * 100:.1f}%",
                        "deducao": faixa["deducao"],
                        "faixa": f"R$ {faixa['min']:,.2f} a R$ {faixa['max']:,.2f}",
                    }

            return {
                "irr": Decimal("0"),
                "base_calculo": base_irrf,
                "aliquota": "0%",
                "faixa": "Não identificada",
            }

        except Exception as e:
            return {"irr": Decimal("0"), "erro": str(e)}

    def calcular_prolabore_completo(
        self, valor_prolabore: Any, dependentes_irrf: int = 0, outras_deducoes: Any = 0
    ) -> Dict[str, Any]:
        """
        Calcula pró-labore completo com todos os tributos

        Args:
            valor_prolabore: Valor bruto do pró-labore
            dependentes_irrf: Número de dependentes para IRRF
            outras_deducoes: Outras deduções (ex: pensão alimentícia)

        Returns:
            Dict com breakdown completo
        """
        send_audit(
            "Calculando pró-labore",
            level="info",
            context={"valor": float(valor_prolabore)},
        )

        try:
            prolabore = Decimal(str(valor_prolabore))
            deducoes = Decimal(str(outras_deducoes))

            # INSS (11%)
            inss = self.calcular_inss_socio(prolabore)

            # IRRF
            resultado_irrf = self.calcular_irrf_socio(prolabore, dependentes_irrf)
            irrf = resultado_irrf.get("irr", Decimal("0"))

            # Total de descontos
            total_descontos = inss + irrf + deducoes

            # Líquido
            liquido = prolabore - total_descontos

            # Alertas
            alertas = []
            if prolabore > self.teto_inss_2026:
                alertas.append(
                    f"Pró-labore acima do teto INSS (R$ {self.teto_inss_2026:,.2f}). "
                    "INSS calculado sobre teto."
                )

            if prolabore < Decimal("1518.00"):  # Salário mínimo 2026
                alertas.append(
                    "Pró-labore abaixo do salário mínimo. Verifique legislação local."
                )

            resultado = {
                "status": "success",
                "prolabore_bruto": prolabore,
                "descontos": {
                    "inss": {
                        "valor": inss,
                        "aliquota": "11%",
                        "teto_aplicado": prolabore > self.teto_inss_2026,
                        "descricao": "INSS Contribuinte Individual",
                    },
                    "irrf": {
                        "valor": irrf,
                        "aliquota": resultado_irrf.get("aliquota", "0%"),
                        "base_calculo": resultado_irrf.get(
                            "base_calculo", Decimal("0")
                        ),
                        "faixa": resultado_irrf.get("faixa", "N/A"),
                        "deducao": resultado_irrf.get("deducao", Decimal("0")),
                        "dependentes": dependentes_irrf,
                        "descricao": "Imposto de Renda Retido na Fonte",
                    },
                    "outras": {
                        "valor": deducoes,
                        "descricao": "Outras deduções (ex: pensão)",
                    },
                },
                "total_descontos": total_descontos,
                "valor_liquido": liquido,
                "percentual_desconto": (
                    (total_descontos / prolabore * 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if prolabore > 0
                    else Decimal("0")
                ),
                "breakdown": [
                    f"Pró-labore Bruto: R$ {prolabore:,.2f}",
                    f"INSS (11%): R$ {inss:,.2f}",
                    f"IRRF ({resultado_irrf.get('aliquota', '0%')}): R$ {irrf:,.2f}",
                    f"Outras Deduções: R$ {deducoes:,.2f}" if deducoes > 0 else None,
                    f"Total Descontos: R$ {total_descontos:,.2f}",
                    f"Valor Líquido: R$ {liquido:,.2f}",
                ],
                "alertas": alertas,
            }

            # Remove None do breakdown
            resultado["breakdown"] = [item for item in resultado["breakdown"] if item]

            send_audit(
                "Pró-labore calculado",
                level="info",
                context={"bruto": float(prolabore), "liquido": float(liquido)},
            )

            return resultado

        except Exception as e:
            send_audit(f"Erro ao calcular pró-labore: {e}", level="error", context={})
            return {
                "status": "error",
                "message": f"Erro ao calcular pró-labore: {str(e)}",
            }

    def calcular_multiplos_socios(self, socios: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calcula pró-labore de múltiplos sócios

        Args:
            socios: Lista de dicts com {"nome", "prolabore", "dependentes"}

        Returns:
            Dict com totais e breakdown por sócio
        """
        send_audit(
            "Calculando pró-labore múltiplos sócios",
            level="info",
            context={"total_socios": len(socios)},
        )

        try:
            total_bruto = Decimal("0")
            total_liquido = Decimal("0")
            total_inss = Decimal("0")
            total_irrf = Decimal("0")
            detalhes_socios = []

            for socio in socios:
                resultado = self.calcular_prolabore_completo(
                    socio.get("prolabore", 0),
                    socio.get("dependentes", 0),
                    socio.get("outras_deducoes", 0),
                )

                if resultado["status"] == "success":
                    bruto = resultado["prolabore_bruto"]
                    liquido = resultado["valor_liquido"]
                    inss = resultado["descontos"]["inss"]["valor"]
                    irrf = resultado["descontos"]["irr"]["valor"]

                    total_bruto += bruto
                    total_liquido += liquido
                    total_inss += inss
                    total_irrf += irrf

                    detalhes_socios.append(
                        {
                            "nome": socio.get("nome", "N/A"),
                            "prolabore_bruto": bruto,
                            "inss": inss,
                            "irr": irrf,
                            "valor_liquido": liquido,
                        }
                    )

            total_descontos = total_inss + total_irrf

            send_audit(
                "Pró-labore múltiplos sócios calculado",
                level="info",
                context={
                    "total_socios": len(socios),
                    "total_bruto": float(total_bruto),
                },
            )

            return {
                "status": "success",
                "total_socios": len(socios),
                "total_prolabore_bruto": total_bruto,
                "total_inss": total_inss,
                "total_irr": total_irrf,
                "total_descontos": total_descontos,
                "total_liquido": total_liquido,
                "socios": detalhes_socios,
                "resumo": [
                    f"Total Sócios: {len(socios)}",
                    f"Total Pró-labore Bruto: R$ {total_bruto:,.2f}",
                    f"Total INSS (11%): R$ {total_inss:,.2f}",
                    f"Total IRRF: R$ {total_irrf:,.2f}",
                    f"Total Líquido: R$ {total_liquido:,.2f}",
                ],
            }

        except Exception as e:
            send_audit(
                f"Erro ao calcular múltiplos sócios: {e}", level="error", context={}
            )
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def simular_prolabore_ideal(
        self, faturamento_mensal: Any, percentual_retirada: float = 0.30
    ) -> Dict[str, Any]:
        """
        Simula pró-labore ideal baseado no faturamento

        Args:
            faturamento_mensal: Faturamento da empresa
            percentual_retirada: % sugerido para pró-labore (padrão: 30%)

        Returns:
            Dict com simulação
        """
        try:
            faturamento = Decimal(str(faturamento_mensal))
            percentual = Decimal(str(percentual_retirada))

            prolabore_sugerido = (faturamento * percentual).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Calcula tributos
            resultado = self.calcular_prolabore_completo(prolabore_sugerido)

            return {
                "status": "success",
                "faturamento_mensal": faturamento,
                "percentual_retirada": f"{percentual * 100:.1f}%",
                "prolabore_sugerido": prolabore_sugerido,
                "valor_liquido": resultado.get("valor_liquido", Decimal("0")),
                "total_descontos": resultado.get("total_descontos", Decimal("0")),
                "detalhes": resultado,
            }

        except Exception as e:
            return {"status": "error", "message": f"Erro na simulação: {str(e)}"}
