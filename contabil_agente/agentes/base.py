"""Base dos agentes: cada agente expõe *ações* (``acao_<nome>``) e devolve sempre um dicionário com ``status``.

``status``: ``ok`` (resultado nos demais campos), ``faltam_dados`` (com ``faltando`` e ``pergunta``) ou ``erro`` (com ``mensagem``).
Nenhum agente inventa valor: dado faltando ou inválido vira ``faltam_dados``/``erro``, nunca um zero silencioso.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from contabil_agente.calc.encargos import FaltamDados
from contabil_agente.calc.errors import CalculoError


class AgenteErro(ValueError):
    """Pedido inválido para o agente (ação inexistente, campo obrigatório ausente ou com formato errado)."""


class AcaoDesconhecida(AgenteErro):
    pass


class Agente:
    nome = "Agente"
    descricao = ""

    def acoes(self) -> Dict[str, str]:
        """``{nome_da_ação: descrição}`` (primeira linha da docstring de cada ``acao_*``)."""
        saida: Dict[str, str] = {}
        for atributo in sorted(dir(self)):
            if atributo.startswith("acao_") and callable(getattr(self, atributo)):
                doc = (getattr(self, atributo).__doc__ or "").strip().splitlines()
                saida[atributo[len("acao_"):]] = doc[0] if doc else ""
        return saida

    def descrever(self) -> Dict[str, Any]:
        return {"agente": self.nome, "descricao": self.descricao, "acoes": self.acoes()}

    def executar(self, acao: str, dados: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        funcao: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = getattr(self, f"acao_{acao}", None)
        if funcao is None:
            raise AcaoDesconhecida(f"{self.nome} não tem a ação {acao!r}. Ações: {', '.join(self.acoes()) or 'nenhuma'}.")
        try:
            resultado = funcao(dados or {})
        except FaltamDados as exc:
            return {"agente": self.nome, "acao": acao, "status": "faltam_dados", "faltando": exc.faltando, "pergunta": exc.pergunta}
        except (CalculoError, AgenteErro) as exc:
            if isinstance(exc, AcaoDesconhecida):
                raise
            return {"agente": self.nome, "acao": acao, "status": "erro", "mensagem": str(exc)}
        return {"agente": self.nome, "acao": acao, "status": "ok", **resultado} if "status" not in resultado else {"agente": self.nome, "acao": acao, **resultado}


def exigir_campo(dados: Dict[str, Any], campo: str, tipo: Optional[type] = None) -> Any:
    valor = dados.get(campo)
    if valor in (None, "", [], {}):
        raise AgenteErro(f"Falta o campo {campo!r}.")
    if tipo is not None and not isinstance(valor, tipo):
        raise AgenteErro(f"O campo {campo!r} precisa ser {tipo.__name__}.")
    return valor
