"""Carregamento e validação das tabelas oficiais (fonte única: data/tabelas.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import CompetenciaSemTabela, DadosInvalidos
from .money import D

ARQUIVO_PADRAO = Path(__file__).resolve().parent / "data" / "tabelas.json"


@dataclass(frozen=True)
class FaixaInss:
    ate: Decimal
    aliquota: Decimal


@dataclass(frozen=True)
class TabelaInss:
    vigencia_inicio: date
    vigencia_fim: Optional[date]
    norma: str
    verificacao: str
    salario_minimo: Decimal
    teto: Decimal
    faixas: Tuple[FaixaInss, ...]


@dataclass(frozen=True)
class FaixaIrrf:
    ate: Optional[Decimal]  # None = sem limite superior
    aliquota: Decimal
    deducao: Decimal


@dataclass(frozen=True)
class ReducaoIrrf:
    norma: str
    ate: Decimal
    valor_maximo: Decimal
    parcial_ate: Decimal
    constante: Decimal
    coeficiente: Decimal


@dataclass(frozen=True)
class TabelaIrrf:
    vigencia_inicio: date
    vigencia_fim: Optional[date]
    norma: str
    verificacao: str
    faixas: Tuple[FaixaIrrf, ...]
    deducao_dependente: Decimal
    desconto_simplificado: Decimal
    reducao: Optional[ReducaoIrrf]


def _data(valor: Optional[str]) -> Optional[date]:
    return date.fromisoformat(valor) if valor else None


def validar(bruto: Dict[str, Any]) -> List[str]:
    """Devolve a lista de problemas encontrados no arquivo de tabelas (vazia = ok)."""
    problemas: List[str] = []

    def vigencias_ok(nome: str, registros: List[Dict[str, Any]]) -> None:
        ordenados = sorted(registros, key=lambda r: r["vigencia_inicio"])
        for anterior, atual in zip(ordenados, ordenados[1:]):
            fim = anterior.get("vigencia_fim")
            if fim is None:
                problemas.append(f"{nome}: registro com vigência aberta não é o último")
            elif date.fromisoformat(fim) >= date.fromisoformat(atual["vigencia_inicio"]):
                problemas.append(f"{nome}: vigências se sobrepõem ({fim} >= {atual['vigencia_inicio']})")

    inss = bruto.get("inss_empregado", [])
    irrf = bruto.get("irrf_mensal", [])
    if not inss:
        problemas.append("inss_empregado: vazio")
    if not irrf:
        problemas.append("irrf_mensal: vazio")
    vigencias_ok("inss_empregado", inss)
    vigencias_ok("irrf_mensal", irrf)

    for reg in inss:
        rotulo = f"inss {reg.get('vigencia_inicio')}"
        faixas = reg.get("faixas", [])
        limites = [D(f["ate"]) for f in faixas]
        if limites != sorted(limites) or len(set(limites)) != len(limites):
            problemas.append(f"{rotulo}: faixas não estão em ordem crescente")
        if faixas and D(reg["teto"]) != D(faixas[-1]["ate"]):
            problemas.append(f"{rotulo}: teto difere do limite da última faixa")
        if faixas and D(reg["salario_minimo"]) != D(faixas[0]["ate"]):
            problemas.append(f"{rotulo}: 1ª faixa deveria terminar no salário mínimo")
        if len(faixas) != 4:
            problemas.append(f"{rotulo}: esperadas 4 faixas, há {len(faixas)}")
        # conferência pela parcela a deduzir publicada (método alternativo da portaria)
        conf = reg.get("parcelas_a_deduzir_conferencia")
        if conf and len(conf) == len(faixas):
            acumulado = D("0")
            anterior = D("0")
            for faixa, parcela in zip(faixas, conf):
                aliq = D(faixa["aliquota"])
                # parcela_a_deduzir(i) = soma_{j<i} (aliq_i - aliq_j) * largura_j
                esperado = D("0")
                anterior = D("0")
                for outra in faixas:
                    if D(outra["ate"]) >= D(faixa["ate"]):
                        break
                    esperado += (aliq - D(outra["aliquota"])) * (D(outra["ate"]) - anterior)
                    anterior = D(outra["ate"])
                if abs(esperado - D(parcela)) > D("0.01"):
                    problemas.append(
                        f"{rotulo}: parcela a deduzir publicada ({parcela}) não bate com o cálculo ({esperado:.2f})"
                    )

    for reg in irrf:
        rotulo = f"irrf {reg.get('vigencia_inicio')}"
        faixas = reg.get("faixas", [])
        if not faixas or faixas[-1]["ate"] is not None:
            problemas.append(f"{rotulo}: a última faixa deve ter 'ate' nulo")
        limites = [D(f["ate"]) for f in faixas[:-1]]
        if limites != sorted(limites):
            problemas.append(f"{rotulo}: faixas fora de ordem")
        # a primeira faixa isenta + desconto simplificado = 25% do limite
        if faixas and D(reg["desconto_simplificado"]) != (D(faixas[0]["ate"]) * D("0.25")).quantize(D("0.01")):
            problemas.append(f"{rotulo}: desconto simplificado deveria ser 25% da 1ª faixa")
        # continuidade: a parcela a deduzir mantém o imposto contínuo entre faixas
        for atual, proxima in zip(faixas, faixas[1:]):
            limite = D(atual["ate"])
            a = limite * D(atual["aliquota"]) - D(atual["deducao"])
            b = limite * D(proxima["aliquota"]) - D(proxima["deducao"])
            if abs(a - b) > D("0.05"):
                problemas.append(f"{rotulo}: descontinuidade no limite {limite} ({a:.2f} x {b:.2f})")
        red = reg.get("reducao")
        if red:
            # a redução parcial deve zerar exatamente em 'parcial_ate' (+- 1 centavo)
            zero = D(red["constante"]) - D(red["coeficiente"]) * D(red["parcial_ate"])
            if abs(zero) > D("0.01"):
                problemas.append(f"{rotulo}: redução não zera em {red['parcial_ate']} (resto {zero:.4f})")
            # e deve ser contínua em 'ate' (5.000): constante - coef*5000 ~ valor_maximo
            em_ate = D(red["constante"]) - D(red["coeficiente"]) * D(red["ate"])
            if abs(em_ate - D(red["valor_maximo"])) > D("0.01"):
                problemas.append(f"{rotulo}: redução descontínua em {red['ate']} ({em_ate:.2f} x {red['valor_maximo']})")
    return problemas


def _construir_inss(reg: Dict[str, Any]) -> TabelaInss:
    return TabelaInss(
        vigencia_inicio=_data(reg["vigencia_inicio"]),
        vigencia_fim=_data(reg.get("vigencia_fim")),
        norma=reg["norma"],
        verificacao=reg["verificacao"],
        salario_minimo=D(reg["salario_minimo"]),
        teto=D(reg["teto"]),
        faixas=tuple(FaixaInss(ate=D(f["ate"]), aliquota=D(f["aliquota"])) for f in reg["faixas"]),
    )


def _construir_irrf(reg: Dict[str, Any]) -> TabelaIrrf:
    red = reg.get("reducao")
    return TabelaIrrf(
        vigencia_inicio=_data(reg["vigencia_inicio"]),
        vigencia_fim=_data(reg.get("vigencia_fim")),
        norma=reg["norma"],
        verificacao=reg["verificacao"],
        faixas=tuple(
            FaixaIrrf(ate=None if f["ate"] is None else D(f["ate"]), aliquota=D(f["aliquota"]), deducao=D(f["deducao"]))
            for f in reg["faixas"]
        ),
        deducao_dependente=D(reg["deducao_dependente"]),
        desconto_simplificado=D(reg["desconto_simplificado"]),
        reducao=None
        if not red
        else ReducaoIrrf(
            norma=red["norma"],
            ate=D(red["ate"]),
            valor_maximo=D(red["valor_maximo"]),
            parcial_ate=D(red["parcial_ate"]),
            constante=D(red["constante"]),
            coeficiente=D(red["coeficiente"]),
        ),
    )


@lru_cache(maxsize=4)
def carregar(caminho: Optional[str] = None) -> Tuple[Tuple[TabelaInss, ...], Tuple[TabelaIrrf, ...]]:
    """Lê e valida o arquivo de tabelas. Falha alto se houver qualquer inconsistência."""
    arquivo = Path(caminho) if caminho else ARQUIVO_PADRAO
    with open(arquivo, "r", encoding="utf-8") as fh:
        bruto = json.load(fh)
    problemas = validar(bruto)
    if problemas:
        raise DadosInvalidos("tabelas.json inválido: " + "; ".join(problemas))
    inss = tuple(_construir_inss(r) for r in bruto["inss_empregado"])
    irrf = tuple(_construir_irrf(r) for r in bruto["irrf_mensal"])
    return inss, irrf


def _escolher(registros, competencia: date, nome: str):
    for reg in registros:
        if reg.vigencia_inicio <= competencia and (reg.vigencia_fim is None or competencia <= reg.vigencia_fim):
            return reg
    inicio = min(r.vigencia_inicio for r in registros)
    raise CompetenciaSemTabela(
        f"Não há tabela de {nome} carregada para {competencia:%m/%Y} "
        f"(a mais antiga começa em {inicio:%m/%Y}). Atualize contabil_agente/calc/data/tabelas.json."
    )


def tabela_inss(competencia: date, caminho: Optional[str] = None) -> TabelaInss:
    return _escolher(carregar(caminho)[0], competencia, "INSS")


def tabela_irrf(competencia: date, caminho: Optional[str] = None) -> TabelaIrrf:
    return _escolher(carregar(caminho)[1], competencia, "IRRF")
