"""Folha mensal (holerite): proventos, INSS, IRRF, vale-transporte, FGTS e líquido.

* INSS e IRRF incidem sobre todos os proventos do mês (salário, adicionais, horas extras e DSR).
* Vale-transporte: desconto de até 6% do salário base, limitado ao custo do VT (Lei 7.418/1985, art. 4º).
* FGTS é encargo do empregador: aparece no resultado mas não reduz o líquido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from .errors import DadosInvalidos
from .fgts import calcular_fgts_mensal
from .inss import calcular_inss
from .irrf import calcular_irrf_mensal
from .money import ZERO, D, nao_negativo, q2

DESCONTO_VT_MAXIMO = Decimal("0.06")


@dataclass(frozen=True)
class ResultadoFolha:
    competencia: date
    proventos: Dict[str, Decimal]
    descontos: Dict[str, Decimal]
    total_proventos: Decimal
    total_descontos: Decimal
    liquido: Decimal
    fgts: Decimal
    tabelas: Dict[str, str]
    explicacao: tuple

    def to_dict(self) -> Dict[str, Any]:
        f = lambda x: float(q2(x))  # noqa: E731
        return {
            "status": "success",
            "competencia": f"{self.competencia:%Y-%m}",
            "proventos": {k: f(v) for k, v in self.proventos.items()},
            "descontos": {k: f(v) for k, v in self.descontos.items()},
            "total_proventos": f(self.total_proventos),
            "total_descontos": f(self.total_descontos),
            "total_liquido": f(self.liquido),
            "fgts_empregador": f(self.fgts),
            "tabelas": self.tabelas,
            "explicacao": list(self.explicacao),
        }


def _valor(dados: Dict[str, Any], nome: str) -> Decimal:
    return nao_negativo(D(dados.get(nome) or 0, nome), nome)


def calcular_folha(
    salario_base,
    competencia: date,
    adicionais_mensais=0,
    horas_extras=0,
    dsr_horas_extras=0,
    outros_proventos=0,
    dependentes: int = 0,
    pensao_alimenticia=0,
    custo_vale_transporte=0,
    outros_descontos=0,
    categoria_fgts: str = "empregado",
    caminho_tabelas: Optional[str] = None,
) -> ResultadoFolha:
    salario = D(salario_base, "salário base")
    if salario <= 0:
        raise DadosInvalidos("O salário base deve ser maior que zero.")
    competencia = date(competencia.year, competencia.month, 1)
    proventos = {
        "salario_base": salario,
        "adicionais": nao_negativo(D(adicionais_mensais, "adicionais"), "adicionais"),
        "horas_extras": nao_negativo(D(horas_extras, "horas extras"), "horas extras"),
        "dsr_horas_extras": nao_negativo(D(dsr_horas_extras, "DSR"), "DSR"),
        "outros_proventos": nao_negativo(D(outros_proventos, "outros proventos"), "outros proventos"),
    }
    proventos = {k: v for k, v in proventos.items() if v > 0 or k == "salario_base"}
    total_proventos = sum(proventos.values(), ZERO)

    inss = calcular_inss(total_proventos, competencia, caminho_tabelas)
    pensao = nao_negativo(D(pensao_alimenticia, "pensão alimentícia"), "pensão alimentícia")
    irrf = calcular_irrf_mensal(
        total_proventos,
        competencia,
        inss=inss.valor,
        dependentes=int(dependentes),
        pensao_alimenticia=pensao,
        caminho_tabelas=caminho_tabelas,
    )
    vt_custo = nao_negativo(D(custo_vale_transporte, "vale-transporte"), "vale-transporte")
    vt_desconto = min(q2(salario * DESCONTO_VT_MAXIMO), vt_custo)

    descontos = {"inss": inss.valor, "irrf": irrf.valor}
    if vt_desconto > 0:
        descontos["vale_transporte"] = vt_desconto
    if pensao > 0:
        descontos["pensao_alimenticia"] = pensao
    outros = nao_negativo(D(outros_descontos, "outros descontos"), "outros descontos")
    if outros > 0:
        descontos["outros_descontos"] = outros
    total_descontos = sum(descontos.values(), ZERO)
    liquido = total_proventos - total_descontos

    fgts = calcular_fgts_mensal(total_proventos, categoria_fgts)
    explicacao = (
        f"Proventos: {q2(total_proventos)} (INSS e IRRF incidem sobre todos).",
        f"INSS {q2(inss.valor)} pela tabela {inss.norma}.",
        f"IRRF {q2(irrf.valor)} (base {q2(irrf.base_calculo)}; opção: {irrf.opcao_deducao}).",
        f"FGTS do empregador: {q2(fgts.valor)} ({fgts.aliquota * 100:.1f}% de {q2(total_proventos)}).",
    )
    if vt_desconto > 0:
        explicacao += (f"Vale-transporte: desconto de {vt_desconto} (menor entre 6% do salário base e o custo).",)

    return ResultadoFolha(
        competencia=competencia,
        proventos=proventos,
        descontos=descontos,
        total_proventos=total_proventos,
        total_descontos=total_descontos,
        liquido=liquido,
        fgts=fgts.valor,
        tabelas={"inss": f"{inss.norma} [{inss.verificacao}]", "irrf": f"{irrf.norma} [{irrf.verificacao}]"},
        explicacao=explicacao,
    )
