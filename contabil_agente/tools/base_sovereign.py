"""BaseSovereignTool: base das ferramentas, com auditoria WORM e proteção pós-quântica reais.

* ``audit`` registra no log da aplicação e, se a ferramenta recebeu uma trilha ``WormAudit``, também na
  trilha encadeada (sem criar arquivos soltos no diretório atual).
* ``proteger`` / ``abrir`` cifram dados com ML-KEM-768 + X25519 + AES-256-GCM (``security.pqc``).
  Não há versão "de mentira": sem chave, levanta erro.
* ``legal_effective_value`` lê valores legais (ex.: salário mínimo) das tabelas do motor ``calc``.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from contabil_agente.calc.tables import tabela_inss
from contabil_agente.security import pqc
from contabil_agente.security.worm_audit import WormAudit

logger = logging.getLogger(__name__)


class BaseSovereignTool:
    def __init__(self, db_pool: Optional[Any] = None, service_name: str = "tool", worm: Optional[WormAudit] = None, tenant: str = "SYSTEM"):
        self.db_pool = db_pool
        self.service_name = service_name
        self.worm = worm
        self.tenant = tenant

    # ----------------------------------------------------------------- auditoria
    def audit(self, event: str, level: str = "info", context: Optional[Dict[str, Any]] = None) -> None:
        getattr(logger, level if level in ("debug", "info", "warning", "error", "critical") else "info")(
            "AUDIT %s %s", f"{self.service_name}.{event}", sorted((context or {}).keys())
        )
        if self.worm is not None:
            self.worm.append(f"{self.service_name}.{event}", context or {}, tenant=self.tenant, ator=self.service_name)

    # ------------------------------------------------------------- criptografia PQ
    def proteger(self, dados: bytes, chave_publica: Dict[str, str], aad: bytes = b"") -> Dict[str, str]:
        envelope = pqc.cifrar_hibrido(chave_publica, dados, aad)
        self.audit("protegido", context={"bytes": len(dados), "key_id": chave_publica.get("id", "")})
        return envelope

    def abrir(self, envelope: Dict[str, str], chave_privada: Dict[str, str], aad: bytes = b"") -> bytes:
        dados = pqc.decifrar_hibrido(chave_privada, envelope, aad)
        self.audit("aberto", context={"bytes": len(dados)})
        return dados

    # ---------------------------------------------------------------- valores legais
    @staticmethod
    def legal_effective_value(chave: str, competencia: Optional[date] = None) -> Optional[Decimal]:
        """``salario_minimo`` ou ``teto_inss`` da competência (mês atual por padrão); outras chaves devolvem ``None``."""
        base = competencia or date.today()
        tabela = tabela_inss(date(base.year, base.month, 1))
        return {"salario_minimo": tabela.salario_minimo, "teto_inss": tabela.teto}.get(chave)
