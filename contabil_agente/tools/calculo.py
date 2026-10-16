"""Extração da classe ToolCalculo do arquivo principal"""

from decimal import Decimal
from typing import Any, Dict

from .calculo_tool import (
    ToolCalculo as RealToolCalculo,
    DadosFuncionario as CT_DadosFuncionario,
    DadosRescisaoCalculo as CT_DadosRescisaoCalculo,
)


class ToolCalculo:
    """Adapter wrapper for the richer `calculo_tool.ToolCalculo` implementation.

    This class keeps the original module-level API while delegating
    implementation to the single source of truth in `calculo_tool.py`.
    """

    def __init__(self, db_pool=None):
        self._impl = RealToolCalculo(db_pool=db_pool)

    # Expose constants from the real implementation for compatibility
    SALARIO_MINIMO = getattr(RealToolCalculo, "SALARIO_MINIMO", Decimal("0"))
    DEDUCAO_DEPENDENTE_IRRF = getattr(
        RealToolCalculo, "DEDUCAO_DEPENDENTE_IRRF", Decimal("0")
    )

    def calcular_inss(self, salario: Decimal) -> Decimal:
        return self._impl.calcular_inss(salario)

    def calcular_irrf(
        self, salario_base: Decimal, dependentes: int = 0, details: bool = False
    ):
        try:
            base = Decimal(str(salario_base))
        except Exception:
            base = Decimal("0")

        if dependentes:
            deducao = getattr(
                self._impl, "deducao_dependente_irr", Decimal("0")
            ) * Decimal(str(dependentes))
            base = max(Decimal("0"), base - deducao)

        irrf = self._impl.calcular_irrf(base)

        if details:
            inss = self._impl.calcular_inss(base)
            return {
                "base_calculo": base.quantize(Decimal("0.01")),
                "irr": irrf.quantize(Decimal("0.01")),
                "inss": inss.quantize(Decimal("0.01")),
            }

        return irrf

    def calcular_13_proporcional(self, salario: Decimal, meses: int) -> Decimal:
        return self._impl.calcular_13_proporcional(salario, meses)

    def calcular_ferias_proporcionais(self, salario: Decimal, meses: int):
        return self._impl.calcular_ferias_proporcionais(salario, meses)

    def calcular_aviso_previo(self, salario: Decimal, anos_trabalhados: int) -> Decimal:
        return self._impl.calcular_aviso_previo(salario, anos_trabalhados)

    def calcular_rescisao(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        return self._impl.calcular_rescisao(dados)

    def calcular_rescisao_completa(
        self, dados_func_or_dict, dados_resc=None
    ) -> Dict[str, Any]:
        # Accept either (DadosFuncionario, DadosRescisaoCalculo) from contabil_agente.models
        # or the calculo_tool's own dataclasses. Convert when necessary.
        if dados_resc is not None:
            func = dados_func_or_dict
            resc = dados_resc
            ct_func = CT_DadosFuncionario(
                nome=getattr(func, "nome", ""),
                cpf=getattr(func, "cp", ""),
                pis=getattr(func, "pis", ""),
                cargo=getattr(func, "cargo", ""),
                salario_base=getattr(func, "salario_base", Decimal("0.00")),
                periculosidade=getattr(func, "periculosidade", False),
                horas_extras=getattr(func, "horas_extras", Decimal("0.00")),
                media_horas_extras=getattr(func, "media_horas_extras", Decimal("0.00")),
                data_admissao=getattr(func, "data_admissao", None),
                data_demissao=getattr(func, "data_demissao", None),
                dependentes_irrf=getattr(
                    func, "dependentes_irr", getattr(func, "dependentes_irr", 0)
                ),
            )

            tipo_val = getattr(resc, "tipo", "sem_justa_causa")

            # Apply high-level rules compatible with calculo_tool.aplicar_regras_por_tipo_rescisao
            if tipo_val == "justa_causa":
                calc_multa = False
                aviso_trab = False
            elif tipo_val == "pedido_demissao":
                calc_multa = False
                aviso_trab = True
            elif tipo_val == "acordo":
                calc_multa = True
                aviso_trab = False
            else:
                calc_multa = getattr(resc, "calcular_multa_fgts", True)
                aviso_trab = getattr(resc, "aviso_previo_trabalhado", False)

            ct_resc = CT_DadosRescisaoCalculo(
                tipo=tipo_val,
                aviso_previo_trabalhado=aviso_trab,
                dias_aviso_previo=getattr(resc, "dias_aviso_previo", 30),
                ferias_vencidas=getattr(resc, "ferias_vencidas", 0),
                ferias_proporcionais=getattr(resc, "ferias_proporcionais", True),
                decimo_terceiro_proporcional=getattr(
                    resc, "decimo_terceiro_proporcional", True
                ),
                calcular_multa_fgts=calc_multa,
                dias_trabalhados_mes=getattr(resc, "dias_trabalhados_mes", 15),
                possui_ferias_vencidas=getattr(resc, "possui_ferias_vencidas", False),
                numero_dependentes_irrf=getattr(resc, "numero_dependentes_irr", 0),
                pensao_alimenticia=getattr(resc, "pensao_alimenticia", Decimal("0.00")),
                outras_deducoes=getattr(resc, "outras_deducoes", Decimal("0.00")),
                meses_trabalhados_ano=getattr(resc, "meses_trabalhados_ano", 0),
                meses_trabalhados_periodo_aquisitivo=getattr(
                    resc, "meses_trabalhados_periodo_aquisitivo", 0
                ),
                meses_trabalhados_total=getattr(resc, "meses_trabalhados_total", 0),
                saldo_fgts_atual=(
                    None
                    if getattr(resc, "saldo_fgts_atual", None)
                    in (None, 0, Decimal("0"), Decimal("0.00"))
                    else getattr(resc, "saldo_fgts_atual")
                ),
            )

            return self._impl.calcular_rescisao_completa(ct_func, ct_resc)

        # Single argument: delegate to executar if dict, or assume already proper types
        if isinstance(dados_func_or_dict, dict):
            return self._impl.executar(dados_func_or_dict)

        # Otherwise assume it's already the calculo_tool dataclass pair; try best-effort
        return self._impl.calcular_rescisao_completa(dados_func_or_dict, dados_resc)

    def __call__(self, dados_func_or_dict, dados_resc=None) -> Dict[str, Any]:
        """Allow calling with either a single dict or (DadosFuncionario, DadosRescisaoCalculo).

        Returns a dict with status, detalhes and explanation for compatibility.
        """
        # Case: passed two objects (func, resc)
        if dados_resc is not None:
            func = dados_func_or_dict
            resc = dados_resc
            dados = {
                "salario": float(getattr(func, "salario_base", 0)),
                "meses_trabalbados": int(getattr(resc, "meses_trabalhados_total", 0)),
                "tipo_rescisao": getattr(resc, "tipo", "sem_justa_causa"),
                # Keep both keys for backward compatibility
                "dependentes_irr": int(getattr(func, "dependentes_irr", 0)),
                "dependentes_irrf": int(getattr(func, "dependentes_irrf", 0)),
            }
            detalhes = self.__class__.calcular_rescisao(dados)
            return {
                "status": "success",
                "detalhes": detalhes,
                "explanation": [
                    f"Cálculo: {detalhes.get('tipo_rescisao', '')} - total líquido R$ {detalhes.get('total_liquido', 0)}"
                ],
            }

        # Single dict case
        detalhes = self.__class__.calcular_rescisao(dados_func_or_dict)
        return {"status": "success", "detalhes": detalhes, "explanation": ["OK"]}
