"""ToolCalculo: fachada fina sobre o motor único ``contabil_agente.calc``.

Não existe mais tabela de INSS/IRRF nem regra de rescisão neste arquivo. Tudo
vem de ``calc`` (tabelas em ``calc/data/tabelas.yaml``). Se a competência não
tem tabela, o cálculo falha com a explicação; nunca estima.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from contabil_agente.calc import CalculoError, calcular_inss, calcular_irrf_mensal
from contabil_agente.calc.money import D, q2
from contabil_agente.calc.rescisao import DadosRescisao, ler_data
from contabil_agente.calc.servico import calcular as calcular_servico

from ..models.funcionario import DadosFuncionario, DadosRescisaoCalculo
from .base_sovereign import BaseSovereignTool

logger = logging.getLogger(__name__)

_ADICIONAL_PERICULOSIDADE = Decimal("0.30")  # CLT art. 193, §1º


def _primeiro_dia_do_mes(data: date) -> date:
    return date(data.year, data.month, 1)


def _erro(mensagem: str, **extra: Any) -> Dict[str, Any]:
    return {"status": "error", "message": mensagem, **extra}


def _padronizar(retorno: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o retorno de ``calc.servico.calcular`` no formato histórico desta ferramenta."""
    status = retorno.get("status")
    if status == "ok":
        resultado = dict(retorno["resultado"])
        resultado["status"] = "success"
        resultado["resumo"] = retorno.get("resumo", "")
        resultado["detalhes"] = {
            chave: resultado[chave]
            for chave in ("total_proventos", "total_descontos", "total_liquido")
            if chave in resultado
        }
        resultado.setdefault("explanation", resultado.get("explicacao", []))
        return resultado
    if status == "faltam_dados":
        return _erro(retorno["pergunta"], faltando=retorno["faltando"], codigo="faltam_dados")
    return _erro(retorno.get("mensagem", "Cálculo não realizado."), codigo=retorno.get("codigo", "calculo"))


class ToolCalculo(BaseSovereignTool):
    """Cálculos trabalhistas e tributários (INSS, IRRF, férias, 13º e rescisão)."""

    def __init__(self, db_pool=None, hoje: Optional[date] = None):
        super().__init__(db_pool=db_pool, service_name="calculadora_trabalhista")
        self._hoje = hoje

    # ------------------------------------------------------------------ util
    def _competencia(self, competencia: Any = None) -> date:
        if competencia is None:
            return _primeiro_dia_do_mes(self._hoje or date.today())
        return _primeiro_dia_do_mes(ler_data(competencia, "competência"))

    def _auditar(self, tipo: str, resultado: Dict[str, Any]) -> None:
        try:
            self.audit(
                "calculo_executado",
                context={"tipo": tipo, "status": resultado.get("status"), "codigo": resultado.get("codigo")},
            )
        except Exception:
            logger.exception("Falha ao gravar auditoria do cálculo")

    # ------------------------------------------------------------- impostos
    def calcular_inss(self, valor: Any, competencia: Any = None) -> Decimal:
        """INSS progressivo do empregado, limitado ao teto da competência."""
        return calcular_inss(valor, self._competencia(competencia)).valor

    def calcular_irrf(
        self,
        rendimentos_tributaveis: Any,
        competencia: Any = None,
        inss: Any = None,
        dependentes: int = 0,
        pensao_alimenticia: Any = 0,
    ) -> Decimal:
        """IRRF mensal sobre ``rendimentos_tributaveis`` (valor bruto, antes das deduções).

        Se ``inss`` não vier, calcula o INSS sobre o mesmo valor. Aplica a redução
        da Lei 15.270/2025 e escolhe entre dedução simplificada e deduções legais.
        """
        comp = self._competencia(competencia)
        if inss is None:
            inss = calcular_inss(rendimentos_tributaveis, comp).valor
        return calcular_irrf_mensal(
            rendimentos_tributaveis,
            comp,
            inss=D(inss, "INSS"),
            dependentes=int(dependentes or 0),
            pensao_alimenticia=pensao_alimenticia or 0,
        ).valor

    # ----------------------------------------------------------------- fluxos
    def executar(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Executa um cálculo a partir de um dicionário.

        ``tipo_calculo`` escolhe o cálculo (rescisao, ferias, decimo_terceiro, inss, irrf).
        Sem ele: se houver data de demissão ou tipo de rescisão, é rescisão; senão,
        é o líquido simples (INSS + IRRF) sobre ``salario_bruto``.
        """
        dados = dict(dados or {})
        if "salario_bruto" in dados and "salario" not in dados and "salario_base" not in dados:
            dados["salario"] = dados["salario_bruto"]
        tipo = str(dados.get("tipo_calculo") or "").strip().lower()
        if not tipo:
            if dados.get("tipo_rescisao") or dados.get("data_demissao"):
                tipo = "rescisao"
            else:
                tipo = "liquido"
        if dados.get("competencia") is None and self._hoje is not None:
            dados["competencia"] = self._hoje.isoformat()

        if tipo == "liquido":
            resultado = self._liquido_simples(dados)
        else:
            resultado = _padronizar(calcular_servico(tipo, dados, self._hoje))
        self._auditar(tipo, resultado)
        return resultado

    def _liquido_simples(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        bruto = dados.get("salario") or dados.get("salario_base")
        if bruto in (None, ""):
            return _erro("Informe o salário bruto.", codigo="faltam_dados", faltando=["salario"])
        try:
            comp = self._competencia(dados.get("competencia"))
            inss = calcular_inss(bruto, comp)
            irrf = calcular_irrf_mensal(
                bruto,
                comp,
                inss=inss.valor,
                dependentes=int(dados.get("dependentes_irrf") or dados.get("dependentes") or 0),
                pensao_alimenticia=dados.get("pensao_alimenticia") or 0,
            )
        except CalculoError as exc:
            return _erro(str(exc), codigo="calculo")
        bruto_dec = D(bruto, "salário bruto")
        liquido = q2(bruto_dec - inss.valor - irrf.valor)
        base = q2(irrf.base_calculo)
        return {
            "status": "success",
            "salario_bruto": float(q2(bruto_dec)),
            "inss": float(inss.valor),
            "base_irrf": float(base),
            "irrf": float(irrf.valor),
            "salario_liquido": float(liquido),
            "tabela_inss": f"{inss.norma} [{inss.verificacao}]",
            "tabela_irrf": f"{irrf.norma} [{irrf.verificacao}]",
            "competencia": f"{comp:%Y-%m}",
        }

    def calcular_rescisao(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Rescisão a partir de um dicionário (mesmos nomes de ``calc.rescisao.dados_de_dict``)."""
        dados = dict(dados or {})
        dados["tipo_calculo"] = "rescisao"
        return self.executar(dados)

    def calcular_rescisao_completa(
        self, funcionario: DadosFuncionario, rescisao: DadosRescisaoCalculo
    ) -> Dict[str, Any]:
        """Rescisão a partir dos modelos ``DadosFuncionario`` e ``DadosRescisaoCalculo``.

        Datas, aviso e verbas são derivados das datas e do tipo; os campos antigos
        ``dias_trabalhados_mes`` e ``meses_trabalhados_*`` não são mais usados, porque
        o motor calcula meses e dias a partir da admissão e da demissão.
        """
        tipo = rescisao.tipo
        if tipo in ("sem_justa_causa", "acordo"):
            aviso = "trabalhado" if rescisao.aviso_previo_trabalhado else "indenizado"
        elif tipo == "pedido_demissao":
            aviso = "trabalhado" if rescisao.aviso_previo_trabalhado else "nao_cumprido"
        else:
            aviso = None

        salario = D(funcionario.salario_base, "salário base")
        adicionais = D(funcionario.valor_insalubridade or 0, "insalubridade")
        if funcionario.periculosidade:
            adicionais += q2(salario * _ADICIONAL_PERICULOSIDADE)

        saldo_fgts = D(rescisao.saldo_fgts_atual or 0, "saldo do FGTS")
        dados = DadosRescisao(
            tipo=tipo,
            data_admissao=funcionario.data_admissao,
            data_demissao=funcionario.data_demissao,
            salario_base=salario,
            aviso_previo=aviso,
            adicionais_mensais=adicionais,
            media_variaveis=D(funcionario.media_horas_extras or 0, "média de variáveis"),
            dependentes_irrf=max(int(funcionario.dependentes_irrf or 0), int(rescisao.numero_dependentes_irrf or 0)),
            pensao_alimenticia=D(rescisao.pensao_alimenticia or 0, "pensão"),
            saldo_fgts=saldo_fgts if saldo_fgts > 0 else None,
            periodos_ferias_vencidas=int(rescisao.ferias_vencidas or 0),
        )
        return self._executar_dados_rescisao(dados)

    def _executar_dados_rescisao(self, dados: DadosRescisao) -> Dict[str, Any]:
        from contabil_agente.calc import calcular_rescisao

        try:
            resultado = calcular_rescisao(dados).to_dict()
        except CalculoError as exc:
            retorno = _erro(str(exc), codigo="calculo")
        else:
            resultado["detalhes"] = {
                chave: resultado[chave] for chave in ("total_proventos", "total_descontos", "total_liquido")
            }
            resultado["explanation"] = resultado.get("explicacao", [])
            retorno = resultado
        self._auditar("rescisao", retorno)
        return retorno


__all__ = ["ToolCalculo", "DadosFuncionario", "DadosRescisaoCalculo"]
