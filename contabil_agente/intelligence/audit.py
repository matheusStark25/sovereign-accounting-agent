"""Auditoria forense do orquestrador de inteligência, gravada na trilha WORM encadeada.

Cada pedido vira uma entrada ``intelligence.pedido`` com ``request_id``, ``session_id``, entrada e saída
(a trilha mascara CPF, CNPJ, e-mail e telefone antes de gravar). Sem uma ``WormAudit`` configurada o
registro não é gravado e isso fica claro no log; falha de gravação é levantada, nunca engolida.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from contabil_agente.security.worm_audit import WormAudit

logger = logging.getLogger(__name__)


class ForensicAudit:
    def __init__(self, worm: Optional[WormAudit] = None, tenant: str = "SYSTEM", ator: str = "orquestrador"):
        self.worm, self.tenant, self.ator = worm, tenant, ator
        if worm is None:
            logger.warning("ForensicAudit sem WormAudit: os pedidos não serão gravados na trilha de auditoria.")

    def record(self, request_id: str, session_id: str, input_sanitized: Any, output: Any) -> Optional[str]:
        if self.worm is None:
            return None
        return self.worm.append(
            "intelligence.pedido",
            {"request_id": request_id, "session_id": session_id, "entrada": input_sanitized, "saida": output},
            tenant=self.tenant,
            ator=self.ator,
        ).id
