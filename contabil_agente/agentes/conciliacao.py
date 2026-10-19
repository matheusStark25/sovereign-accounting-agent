"""ReconciliationAgent: confronta o que a folha diz com o que foi recolhido (guias) e com o que o motor calcula.

Conciliações (todas em ``Decimal``, com tolerância de centavos por holerite, nunca por percentual "de olho"):

* ``fgts``: Σ(8% da remuneração de cada holerite) × valor da guia do FGTS;
* ``inss``: Σ(INSS retido nos holerites) × total da GPS (a GPS inclui a parte patronal, então ela deve ser **maior ou igual**);
* ``irrf``: Σ(IRRF retido nos holerites) × principal do DARF (código da receita do trabalho);
* ``fechamento``: roda as três de uma vez e junta o veredito.

Sem os documentos necessários a conferência não acontece (``sem_base``): não existe "conciliado por falta de dados".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from contabil_agente.calc.fgts import calcular_fgts_mensal
from contabil_agente.calc.money import ZERO, D, q2

from .base import Agente, AgenteErro

CENTAVO = Decimal("0.01")
CODIGOS_IRRF_TRABALHO = {"0561", "0588"}  # rendimentos do trabalho assalariado / sem vínculo


def _valor(d: Dict[str, Any], *campos: str) -> Optional[Decimal]:
    for campo in campos:
        if d.get(campo) not in (None, ""):
            return D(d[campo], campo)
    return None


def _lista(dados: Dict[str, Any], campo: str) -> List[Dict[str, Any]]:
    itens = dados.get(campo)
    if itens in (None, ""):
        return []
    if not isinstance(itens, list) or not all(isinstance(i, dict) for i in itens):
        raise AgenteErro(f"O campo {campo!r} precisa ser uma lista de documentos (objetos).")
    return itens


def _item(conferencia: str, esperado: Decimal, encontrado: Decimal, tolerancia: Decimal, observacao: str = "", minimo: bool = False) -> Dict[str, Any]:
    """``minimo=True``: o encontrado precisa ser maior ou igual ao esperado (ex.: GPS contém também a parte patronal)."""
    diferenca = q2(encontrado - esperado)
    ok = diferenca >= -tolerancia if minimo else abs(diferenca) <= tolerancia
    return {
        "conferencia": conferencia, "esperado": str(q2(esperado)), "encontrado": str(q2(encontrado)),
        "diferenca": str(diferenca), "tolerancia": str(q2(tolerancia)), "ok": ok, "observacao": observacao,
    }


def _veredito(itens: List[Dict[str, Any]]) -> str:
    if not itens:
        return "sem_base"
    return "conciliado" if all(i["ok"] for i in itens) else "divergente"


class ReconciliationAgent(Agente):
    nome = "ReconciliationAgent"
    descricao = (
        "Concilia holerites com as guias recolhidas (FGTS, INSS/GPS e IRRF/DARF) e aponta a diferença em reais. "
        "Sem os documentos necessários, diz que não há base: não dá o visto por falta de dados."
    )

    def acao_fgts(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Σ 8% dos holerites × guia do FGTS: ``{"holerites": [...], "guia_fgts": {"valor_fgts": ...}}``."""
        holerites, guia = _lista(dados, "holerites"), dados.get("guia_fgts")
        itens = self._fgts(holerites, guia, dados.get("categoria", "empregado"))
        return {"veredito": _veredito(itens), "itens": itens}

    def acao_inss(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Σ INSS retido nos holerites × GPS (a GPS deve cobrir ao menos o retido)."""
        itens = self._inss(_lista(dados, "holerites"), dados.get("gps"))
        return {"veredito": _veredito(itens), "itens": itens}

    def acao_irrf(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Σ IRRF retido nos holerites × principal do DARF do trabalho (0561/0588)."""
        itens = self._irrf(_lista(dados, "holerites"), dados.get("darf"))
        return {"veredito": _veredito(itens), "itens": itens}

    def acao_fechamento(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Roda FGTS, INSS e IRRF de uma vez para a competência."""
        holerites = _lista(dados, "holerites")
        itens = (
            self._fgts(holerites, dados.get("guia_fgts"), dados.get("categoria", "empregado"))
            + self._inss(holerites, dados.get("gps"))
            + self._irrf(holerites, dados.get("darf"))
        )
        feitas = {i["conferencia"].split(":")[0] for i in itens}
        return {"veredito": _veredito(itens), "itens": itens, "conferencias_feitas": sorted(feitas),
                "divergencias": [i for i in itens if not i["ok"]]}

    # ------------------------------------------------------------------ conferências
    @staticmethod
    def _fgts(holerites: List[Dict[str, Any]], guia: Optional[Dict[str, Any]], categoria: str) -> List[Dict[str, Any]]:
        if not holerites or not isinstance(guia, dict):
            return []
        guia_valor = _valor(guia, "valor_fgts", "valor", "total")
        if guia_valor is None:
            return []
        esperado, sem_base = ZERO, 0
        for h in holerites:
            base = _valor(h, "total_proventos", "remuneracao", "base_fgts")
            if base is None:
                sem_base += 1
                continue
            esperado += calcular_fgts_mensal(base, categoria).valor
        if sem_base == len(holerites):
            return []
        obs = f"{sem_base} holerite(s) sem total de proventos ficaram de fora." if sem_base else ""
        itens = [_item("FGTS: 8% da remuneração dos holerites × guia", esperado, guia_valor, CENTAVO * (len(holerites) - sem_base), obs)]
        retido = [(_valor(h, "fgts")) for h in holerites]
        if all(v is not None for v in retido):  # o próprio holerite informa o FGTS depositado: confere com a guia também
            itens.append(_item("FGTS: soma do FGTS informado nos holerites × guia", sum(retido, ZERO), guia_valor, CENTAVO * len(holerites)))
        return itens

    @staticmethod
    def _inss(holerites: List[Dict[str, Any]], gps: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not holerites or not isinstance(gps, dict):
            return []
        total_gps = _valor(gps, "total", "valor_inss", "valor")
        retidos = [_valor(h, "inss") for h in holerites]
        if total_gps is None or all(v is None for v in retidos):
            return []
        soma = sum((v for v in retidos if v is not None), ZERO)
        return [_item("INSS: retido nos holerites × GPS (a GPS inclui a parte patronal: precisa ser ≥ ao retido)", soma, total_gps,
                      CENTAVO * len(holerites), minimo=True)]

    @staticmethod
    def _irrf(holerites: List[Dict[str, Any]], darf: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not holerites or not isinstance(darf, dict):
            return []
        codigo = str(darf.get("codigo_receita") or "").strip()
        principal = _valor(darf, "valor_principal", "principal", "total")
        retidos = [_valor(h, "irrf") for h in holerites]
        if principal is None or all(v is None for v in retidos):
            return []
        soma = sum((v for v in retidos if v is not None), ZERO)
        obs = "" if codigo in CODIGOS_IRRF_TRABALHO else f"Código da receita {codigo or 'não informado'}: confira se é o do IRRF do trabalho (0561 ou 0588)."
        return [_item("IRRF: retido nos holerites × principal do DARF", soma, principal, CENTAVO * len(holerites), obs)]
