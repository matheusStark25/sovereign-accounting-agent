"""Orquestrador: roda um plano de passos entre os agentes, passando o resultado de um passo para o seguinte.

Um passo é ``{"agente": "TaxAgent", "acao": "calcular", "dados": {...}}``. Dentro de ``dados``, uma string inteira no formato
``"$N.caminho.do.campo"`` é trocada pelo valor do campo ``caminho.do.campo`` do resultado do passo N (começando em 1), mantendo o
tipo (número continua número). O plano para no primeiro passo que não der ``ok``, a não ser que ele traga
``"continuar_em_erro": true``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .base import AcaoDesconhecida, Agente, AgenteErro

_REF = re.compile(r"^\$(\d+)((?:\.[A-Za-z0-9_]+)*)$")


def _resolver(valor: Any, resultados: List[Dict[str, Any]]) -> Any:
    if isinstance(valor, str):
        m = _REF.match(valor)
        if not m:
            return valor
        n = int(m.group(1))
        if not 1 <= n <= len(resultados):
            raise AgenteErro(f"Referência {valor!r}: o passo {n} ainda não rodou.")
        atual: Any = resultados[n - 1]
        for parte in [p for p in m.group(2).split(".") if p]:
            if isinstance(atual, dict) and parte in atual:
                atual = atual[parte]
            elif isinstance(atual, list) and parte.isdigit() and int(parte) < len(atual):
                atual = atual[int(parte)]
            else:
                raise AgenteErro(f"Referência {valor!r}: o caminho {parte!r} não existe no resultado do passo {n}.")
        return atual
    if isinstance(valor, dict):
        return {k: _resolver(v, resultados) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_resolver(v, resultados) for v in valor]
    return valor


class OrquestradorDeAgentes:
    def __init__(self, agentes: Dict[str, Agente], max_passos: int = 10):
        self.agentes, self.max_passos = dict(agentes), max_passos

    def catalogo(self) -> List[Dict[str, Any]]:
        return [a.descrever() for a in self.agentes.values()]

    def executar(self, passos: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(passos, list) or not passos:
            raise AgenteErro("Informe ao menos um passo.")
        if len(passos) > self.max_passos:
            raise AgenteErro(f"No máximo {self.max_passos} passos por plano.")
        resultados: List[Dict[str, Any]] = []
        interrompido_em = None
        for n, passo in enumerate(passos, 1):
            if not isinstance(passo, dict) or "agente" not in passo or "acao" not in passo:
                raise AgenteErro(f"Passo {n}: use {{\"agente\": ..., \"acao\": ..., \"dados\": {{...}}}}.")
            nome, acao = str(passo["agente"]), str(passo["acao"])
            agente = self.agentes.get(nome)
            try:
                if agente is None:
                    raise AgenteErro(f"Agente desconhecido: {nome!r}. Use: {', '.join(self.agentes)}.")
                resposta = agente.executar(acao, _resolver(passo.get("dados") or {}, resultados))
            except AcaoDesconhecida as exc:
                resposta = {"agente": nome, "acao": acao, "status": "erro", "mensagem": str(exc)}
            except AgenteErro as exc:
                resposta = {"agente": nome, "acao": acao, "status": "erro", "mensagem": str(exc)}
            resultados.append({"passo": n, **resposta})
            if resposta["status"] != "ok" and not passo.get("continuar_em_erro"):
                interrompido_em = n
                break
        todos_ok = interrompido_em is None and all(r["status"] == "ok" for r in resultados)
        return {
            "status": "ok" if todos_ok else ("interrompido" if interrompido_em else "ok_com_erros"),
            "interrompido_no_passo": interrompido_em, "passos": resultados,
        }
