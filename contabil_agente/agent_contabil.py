"""AgenteContabil - Orquestrador principal do projeto

Este módulo tem responsabilidade única: orquestrar chamadas às ferramentas
de cálculo, geração de PDF, assinatura/hash e auditoria.

O código aqui deve ser enxuto, orientado a objetos, e delegar lógica às ferramentas
existentes no pacote `contabil_agente.tools`.

Nota: ferramentas (Calculo, PDF, Assinatura, Hash, Auditoria) são importadas com
fallbacks suaves para permitir execução parcial em ambientes de desenvolvimento.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import signal
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

# Adiciona o diretório pai ao path para permitir importações
pasta_pai = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if pasta_pai not in sys.path:
    sys.path.insert(0, pasta_pai)

# Logger básico para o orquestrador
logger = logging.getLogger("contabil_agente.agent_contabil")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# --- Group D integrations ---
try:
    from core.settings import settings
except Exception:
    settings = None

# Export application Config for legacy tests that import `agent_contabil.Config`
try:
    from contabil_agente.config.config_new import Config  # type: ignore
except Exception:
    try:
        from contabil_agente.config.settings import Config  # type: ignore
    except Exception:
        Config = None  # type: ignore

try:
    from governance.redaction import RedactionFilter

    # install redaction filter globally so all logs are sanitized
    logging.getLogger().addFilter(RedactionFilter())
except Exception:
    logger.warning("Redaction filter unavailable")
try:
    from backend.app import app, _vault, _audit_logger, _start_cleanup, _graceful_shutdown, _intelligence  # type: ignore
except Exception:
    app = None
    _vault = None
    _audit_logger = None

    def _start_cleanup(*a, **kw):
        return None

    def _graceful_shutdown(signum=None, frame=None):
        return None

    _intelligence = None


# NOTE: Register signal handlers only when running as a script (not on import).
# Registering handlers at import time can cause test runners and hosting
# environments to receive and propagate signals unexpectedly.

# --- Persona: Maria Helena (Senior Auditor) system prompt ---
SYSTEM_PROMPT_MARIA_HELENA = """
Maria Helena - Auditoria Sênior

Regras:
1) Especialidade: Responda apenas com conhecimento técnico tributário e contábil. Seja preciso.
2) Proibição de Chute: Nunca invente valores ou regras; se desconhecido, peça confirmação ou dados oficiais.
3) Rastreabilidade: Todas as decisões devem ser registradas com `request_id` e `session_id`.
4) Confirmação: Solicite confirmação explícita quando valores forem informados manualmente.
5) Formatação BRL: Sempre apresente valores em formato BRL `R$ 1.234,56`.
6) Ambiguidade: Quando múltiplas fontes conflitarem, explique precedência e escolha baseada em peso/tempo.
7) Memória SQLite: Use cache local para memória de sessão, registre histórico de alterações.
8) Decisão Executiva: Dê uma única recomendação executiva clara (sim/não, valor númerico) quando possível.
9) Tom de Auditoria: Seja breve, sem emojis, registre logs de auditoria para cada passo.
"""

# utilities extracted to contabil_agente.utils
from contabil_agente.utils import (
    parse_brl_to_float,
    format_brl,
    _is_approximate_text,
    _normalize_k_suffix,
    safe_decimal,
    _is_small_talk,
)

# persona moved to separate module
from contabil_agente.persona import (
    SYSTEM_PROMPT_MARIA_HELENA,
    process_intelligence_request_persona,
)

# calculations moved to separate module
from contabil_agente.calculations import (
    calcular_13_salario,
    calcular_ferias,
    calcular_rescisao,
    validar_data,
)

# Import das ferramentas do projeto - ajustar caminhos se necessário
try:
    from contabil_agente.tools.calculo_tool import (  # type: ignore
        DadosFuncionario,
        DadosRescisaoCalculo,
        ToolCalculo,
    )
except Exception:
    ToolCalculo = None  # type: ignore

    import importlib

    DadosFuncionario = None  # type: ignore
    DadosRescisaoCalculo = None  # type: ignore

try:
    from contabil_agente.tools.pdf_tool import ToolPDF  # type: ignore
except Exception:
    ToolPDF = None  # type: ignore

try:
    from contabil_agente.tools.assinatura_tool import ToolAssinatura  # type: ignore
except Exception:
    ToolAssinatura = None  # type: ignore

try:
    from contabil_agente.utils.audit import send_audit  # type: ignore
except Exception:
    send_audit = None  # type: ignore


# Try to import IntelligenceOrchestrator, fallback to None if not available


# Try to import IntelligenceOrchestrator using importlib, fallback to None if not available
IntelligenceOrchestrator = None
try:
    orchestrator_module = importlib.import_module("intelligence.orchestrator")
    IntelligenceOrchestrator = getattr(
        orchestrator_module, "IntelligenceOrchestrator", None
    )
except Exception:
    IntelligenceOrchestrator = None

# do not import document_service at module import time; import dynamically in fallback
doc_service = None

# AgenteContabil class moved to contabil_agente.agent
from contabil_agente.agent import AgenteContabil


# Pequeno runner para desenvolvimento
def _demo_run():
    agent = AgenteContabil()
    example = {"salario_bruto": 3000.0, "meses_trabalhados": 12}
    try:
        out = agent.processar_pedido(example, meta={"request_id": "demo-1"})
        print("Demo output:", json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        print("Demo run failed:", e)


if __name__ == "__main__":
    # Register graceful shutdown handlers only when executed as a standalone script
    try:
        signal.signal(signal.SIGTERM, _graceful_shutdown)
        signal.signal(signal.SIGINT, _graceful_shutdown)
    except Exception:
        logger.info("Signal handlers not available in this environment")

    _demo_run()


# Compatibility helpers (exported for tests)
def calcular_13_salario(salario: float, meses_trabalhados: int) -> dict:
    try:
        meses = min(max(int(meses_trabalhados), 0), 12)
        salario_dec = safe_decimal(salario)
        valor = (salario_dec / Decimal("12")) * safe_decimal(meses)
        return {"valor_bruto": float(valor.quantize(Decimal("0.01"))), "meses": meses}
    except Exception:
        return {"valor_bruto": 0.0, "meses": 0}


def calcular_ferias(
    salario: float,
    dias_ferias: int = 30,
    abono_pecuniario: bool = False,
    dias_abono: int = 0,
) -> dict:
    try:
        salario_dec = safe_decimal(salario)
        dias = max(int(dias_ferias), 0)
        base = (salario_dec / Decimal("30")) * Decimal(str(dias))
        terco = base / Decimal("3")
        abono = (
            (salario_dec / Decimal("30")) * Decimal(str(dias_abono))
            if abono_pecuniario
            else Decimal("0")
        )
        total = (base + terco + abono).quantize(Decimal("0.01"))
        return {
            "total_ferias": float(total),
            "dias_ferias": dias,
            "dias_abono": int(dias_abono) if abono_pecuniario else 0,
            "abono": float(abono.quantize(Decimal("0.01"))) if abono > 0 else 0,
            "terco_constitucional": float(terco.quantize(Decimal("0.01"))),
        }
    except Exception:
        return {
            "total_ferias": 0.0,
            "dias_ferias": dias_ferias,
            "dias_abono": 0,
            "abono": 0,
            "terco_constitucional": 0.0,
        }


def calcular_rescisao(
    salario: float,
    meses_trabalhados: int,
    tipo: str = "sem_justa_causa",
    saldo_fgts: float = 0.0,
) -> dict:
    try:
        salario_dec = safe_decimal(salario)
        meses = max(int(meses_trabalhados), 0)

        aviso = salario_dec if tipo == "sem_justa_causa" else Decimal("0")

        ferias_base = (salario_dec / Decimal("12")) * Decimal(str(min(meses, 12)))
        ferias_prop = (ferias_base + (ferias_base / Decimal("3"))).quantize(
            Decimal("0.01")
        )

        decimo = (salario_dec / Decimal("12")) * Decimal(str(min(meses, 12)))
        decimo = decimo.quantize(Decimal("0.01"))

        multa = (
            safe_decimal(saldo_fgts) * Decimal("0.40")
            if tipo == "sem_justa_causa"
            else Decimal("0")
        )

        total = (
            aviso + ferias_prop + decimo + Decimal(str(saldo_fgts)) + multa
        ).quantize(Decimal("0.01"))

        return {
            "aviso_previo": float(aviso),
            "ferias_proporcionais": float(ferias_prop),
            "decimo_terceiro": float(decimo),
            "multa_fgts": float(multa.quantize(Decimal("0.01"))),
            "total": float(total),
        }
    except Exception:
        return {
            "aviso_previo": 0,
            "ferias_proporcionais": 0,
            "decimo_terceiro": 0,
            "multa_fgts": 0,
            "total": 0,
        }


def validar_data(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            datetime.strptime(s, fmt)
            return True
        except Exception:
            continue
    return False


# calculation helpers moved to contabil_agente.calculations
# (kept imported above for backwards-compatibility)

# Backwards-compatibility: prefer backend.app for canonical app and infra
try:
    from backend.app import app, _vault, _audit_logger, _start_cleanup, _graceful_shutdown, _intelligence  # type: ignore
except Exception:
    # fall back to original app modules when backend shim unavailable
    try:
        from contabil_agente.app_api import app  # type: ignore
    except Exception:
        try:
            from contabil_agente.app import app as legacy_app  # type: ignore

            app = legacy_app
        except Exception:
            app = None
    _vault = None
    _audit_logger = None

    def _start_cleanup(*a, **kw):
        return None

    def _graceful_shutdown(signum=None, frame=None):
        return None

    _intelligence = None


def process_intelligence_request(
    session_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Adapter to run the IntelligenceOrchestrator with asyncio timeout and per-session isolation.

    - Uses a 30s timeout.
    - Raises RuntimeError if orchestrator unavailable or session locked.
    """
    if _intelligence is None:
        raise RuntimeError("IntelligenceOrchestrator not available")

    import asyncio

    async def _run():
        return await _intelligence.handle(session_id, payload, timeout=30)

    loop = None
    try:
        # Use running loop if exists, otherwise create a new one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # we are in an async context; create a task and wait with timeout
            coro = asyncio.wait_for(_run(), timeout=30)
            task = asyncio.ensure_future(coro)
            # blocking wait (this should be avoided in real servers)
            return asyncio.get_event_loop().run_until_complete(task)
        else:
            return asyncio.run(asyncio.wait_for(_run(), timeout=30))
    except asyncio.TimeoutError:
        logger.exception("Intelligence processing timed out for session %s", session_id)
        return {"status": "timeout"}
    except RuntimeError as e:
        # session lock or other runtime errors propagated
        logger.warning("Intelligence request blocked/failed: %s", e)
        return {"status": "blocked", "reason": str(e)}
    except Exception:
        logger.exception("Unhandled error in intelligence adapter")
        return {"status": "error"}


# persona implementation moved to contabil_agente.persona
