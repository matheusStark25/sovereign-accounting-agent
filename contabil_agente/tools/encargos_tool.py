"""
ToolEncargosPatronais - Cálculo de encargos patronais
Calcula INSS patronal, RAT, Terceiros, FGTS
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

from utils.audit import send_audit


class ToolEncargosPatronais:
    """
    Ferramenta para cálculo de encargos patronais (empresa)

    Encargos calculados:
    - INSS Patronal: 20% sobre folha de pagamento
    - RAT (Risco Ambiental do Trabalho): 1%, 2% ou 3% conforme atividade
    - Terceiros (Sistema S): 5.8% (SESI, SENAI, SEBRAE, etc)
    - FGTS: 8% sobre salário bruto
    - Salário Educação: 2.5% sobre folha
    """

    def __init__(self):
        """Inicializa ferramenta de encargos patronais"""
        # Tabelas de alíquotas (2026)
        self.aliquotas = {
            "inss_patronal": Decimal("0.20"),  # 20%
            "rat_minimo": Decimal("0.01"),  # 1% (risco leve)
            "rat_medio": Decimal("0.02"),  # 2% (risco médio)
            "rat_grave": Decimal("0.03"),  # 3% (risco grave)
            "terceiros": Decimal("0.058"),  # 5.8%
            "fgts": Decimal("0.08"),  # 8%
            "salario_educacao": Decimal("0.025"),  # 2.5%
        }

        # Classificação de atividades por RAT
        self.classificacao_rat = {
            "leve": ["escritorio", "consultoria", "administracao", "servicos"],
            "medio": ["comercio", "saude", "educacao"],
            "grave": ["construcao", "industria", "mineracao", "transporte"],
        }

        send_audit("ToolEncargosPatronais inicializado", level="info", context={})

    def determinar_rat(self, atividade: str) -> Decimal:
        """
        Determina alíquota RAT baseada na atividade

        Args:
            atividade: Tipo de atividade da empresa

        Returns:
            Alíquota RAT aplicável
        """
        atividade_lower = atividade.lower()

        for risco, atividades in self.classificacao_rat.items():
            if any(atv in atividade_lower for atv in atividades):
                if risco == "leve":
                    return self.aliquotas["rat_minimo"]
                elif risco == "medio":
                    return self.aliquotas["rat_medio"]
                else:
                    return self.aliquotas["rat_grave"]

        # Padrão: risco médio
        return self.aliquotas["rat_medio"]

    def calcular_encargos_completos(
        self,
        salario_bruto: Any,
        atividade_empresa: str = "servicos",
        incluir_terceiros: bool = True,
        incluir_salario_educacao: bool = True,
    ) -> Dict[str, Any]:
        """
        Calcula todos os encargos patronais

        Args:
            salario_bruto: Salário bruto do funcionário
            atividade_empresa: Atividade para determinar RAT
            incluir_terceiros: Se True, calcula Sistema S
            incluir_salario_educacao: Se True, calcula Salário Educação

        Returns:
            Dict com breakdown de todos os encargos
        """
        send_audit(
            "Calculando encargos patronais",
            level="info",
            context={"salario": float(salario_bruto)},
        )

        try:
            # Converte para Decimal
            salario = Decimal(str(salario_bruto))

            # INSS Patronal (20%)
            inss_patronal = (salario * self.aliquotas["inss_patronal"]).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # RAT (1%, 2% ou 3%)
            rat_aliquota = self.determinar_rat(atividade_empresa)
            rat = (salario * rat_aliquota).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Terceiros / Sistema S (5.8%)
            terceiros = Decimal("0")
            if incluir_terceiros:
                terceiros = (salario * self.aliquotas["terceiros"]).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            # FGTS (8%)
            fgts = (salario * self.aliquotas["fgts"]).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Salário Educação (2.5%)
            salario_educacao = Decimal("0")
            if incluir_salario_educacao:
                salario_educacao = (
                    salario * self.aliquotas["salario_educacao"]
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Total
            total_encargos = inss_patronal + rat + terceiros + fgts + salario_educacao

            # Percentual total
            percentual_total = (total_encargos / salario * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            resultado = {
                "status": "success",
                "salario_bruto": salario,
                "encargos": {
                    "inss_patronal": {
                        "valor": inss_patronal,
                        "aliquota": "20%",
                        "descricao": "INSS Patronal",
                    },
                    "rat": {
                        "valor": rat,
                        "aliquota": f"{rat_aliquota * 100:.1f}%",
                        "descricao": f"RAT ({atividade_empresa})",
                    },
                    "terceiros": {
                        "valor": terceiros,
                        "aliquota": "5.8%",
                        "descricao": "Sistema S (SESI, SENAI, etc)",
                    },
                    "fgts": {"valor": fgts, "aliquota": "8%", "descricao": "FGTS"},
                    "salario_educacao": {
                        "valor": salario_educacao,
                        "aliquota": "2.5%",
                        "descricao": "Salário Educação",
                    },
                },
                "total_encargos": total_encargos,
                "percentual_total": percentual_total,
                "custo_total_funcionario": salario + total_encargos,
                "breakdown": [
                    f"INSS Patronal (20%): R$ {inss_patronal:,.2f}",
                    f"RAT ({rat_aliquota * 100:.1f}%): R$ {rat:,.2f}",
                    (
                        f"Terceiros (5.8%): R$ {terceiros:,.2f}"
                        if incluir_terceiros
                        else None
                    ),
                    f"FGTS (8%): R$ {fgts:,.2f}",
                    (
                        f"Salário Educação (2.5%): R$ {salario_educacao:,.2f}"
                        if incluir_salario_educacao
                        else None
                    ),
                    f"Total Encargos: R$ {total_encargos:,.2f} ({percentual_total}%)",
                    f"Custo Total: R$ {salario + total_encargos:,.2f}",
                ],
            }

            # Remove None do breakdown
            resultado["breakdown"] = [item for item in resultado["breakdown"] if item]

            send_audit(
                "Encargos calculados",
                level="info",
                context={
                    "total_encargos": float(total_encargos),
                    "percentual": float(percentual_total),
                },
            )

            return resultado

        except Exception as e:
            send_audit(f"Erro ao calcular encargos: {e}", level="error", context={})
            return {
                "status": "error",
                "message": f"Erro ao calcular encargos: {str(e)}",
            }

    def calcular_folha_pagamento_total(
        self, funcionarios: list[Dict[str, Any]], atividade_empresa: str = "servicos"
    ) -> Dict[str, Any]:
        """
        Calcula encargos de toda a folha de pagamento

        Args:
            funcionarios: Lista de dicts com {"nome", "salario"}
            atividade_empresa: Atividade da empresa

        Returns:
            Dict com totais e breakdown por funcionário
        """
        send_audit(
            "Calculando folha de pagamento completa",
            level="info",
            context={"total_funcionarios": len(funcionarios)},
        )

        try:
            total_salarios = Decimal("0")
            total_encargos = Decimal("0")
            detalhes_funcionarios = []

            for func in funcionarios:
                salario = Decimal(str(func.get("salario", 0)))
                resultado = self.calcular_encargos_completos(
                    salario, atividade_empresa=atividade_empresa
                )

                if resultado["status"] == "success":
                    total_salarios += salario
                    total_encargos += resultado["total_encargos"]

                    detalhes_funcionarios.append(
                        {
                            "nome": func.get("nome", "N/A"),
                            "cargo": func.get("cargo", "N/A"),
                            "salario": salario,
                            "encargos": resultado["total_encargos"],
                            "custo_total": resultado["custo_total_funcionario"],
                        }
                    )

            custo_total_folha = total_salarios + total_encargos

            send_audit(
                "Folha de pagamento calculada",
                level="info",
                context={
                    "total_funcionarios": len(funcionarios),
                    "custo_total": float(custo_total_folha),
                },
            )

            return {
                "status": "success",
                "total_funcionarios": len(funcionarios),
                "total_salarios": total_salarios,
                "total_encargos": total_encargos,
                "custo_total_folha": custo_total_folha,
                "percentual_encargos": (
                    (total_encargos / total_salarios * 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if total_salarios > 0
                    else Decimal("0")
                ),
                "funcionarios": detalhes_funcionarios,
                "resumo": [
                    f"Total Funcionários: {len(funcionarios)}",
                    f"Total Salários: R$ {total_salarios:,.2f}",
                    f"Total Encargos: R$ {total_encargos:,.2f}",
                    f"Custo Total da Folha: R$ {custo_total_folha:,.2f}",
                ],
            }

        except Exception as e:
            send_audit(f"Erro ao calcular folha: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def calcular_provisao_13_ferias(
        self, salario_bruto: Any, meses: int = 12
    ) -> Dict[str, Any]:
        """
        Calcula provisão de 13º salário e férias + encargos

        Args:
            salario_bruto: Salário mensal
            meses: Meses de provisão (padrão: 12)

        Returns:
            Dict com valores provisionados
        """
        send_audit("Calculando provisões", level="info", context={})

        try:
            salario = Decimal(str(salario_bruto))

            # 13º salário (8.33% ao mês)
            decimo_terceiro_mes = (salario * Decimal("0.0833")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Férias + 1/3 (11.11% ao mês)
            ferias_mes = (salario * Decimal("0.1111")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Encargos sobre 13º e férias
            base_encargos = decimo_terceiro_mes + ferias_mes
            encargos_provisao = (base_encargos * Decimal("0.208")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )  # 20.8% médio

            total_provisao_mensal = decimo_terceiro_mes + ferias_mes + encargos_provisao
            total_provisao_anual = total_provisao_mensal * meses

            return {
                "status": "success",
                "provisao_mensal": {
                    "decimo_terceiro": decimo_terceiro_mes,
                    "ferias": ferias_mes,
                    "encargos": encargos_provisao,
                    "total": total_provisao_mensal,
                },
                "provisao_anual": {
                    "decimo_terceiro": decimo_terceiro_mes * meses,
                    "ferias": ferias_mes * meses,
                    "encargos": encargos_provisao * meses,
                    "total": total_provisao_anual,
                },
                "breakdown": [
                    f"13º Salário (mensal): R$ {decimo_terceiro_mes:,.2f}",
                    f"Férias + 1/3 (mensal): R$ {ferias_mes:,.2f}",
                    f"Encargos (mensal): R$ {encargos_provisao:,.2f}",
                    f"Provisão Mensal Total: R$ {total_provisao_mensal:,.2f}",
                    f"Provisão Anual Total: R$ {total_provisao_anual:,.2f}",
                ],
            }

        except Exception as e:
            send_audit(f"Erro ao calcular provisões: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}
