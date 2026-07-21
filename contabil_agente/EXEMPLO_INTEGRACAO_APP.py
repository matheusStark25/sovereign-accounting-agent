import logging
import os
from datetime import datetime
from flask import Flask  # type: ignore[reportMissingImports]

app = Flask(__name__)
logger = logging.getLogger(__name__)


def _stub_register_job_api(app):
    pass


class _StubWorkflowManager:
    def configurar_agendamentos(self):
        pass


"""
Exemplo de Integração no app.py
Adicione estas linhas ao seu app.py existente
"""

# ===== ADICIONAR APÓS OS IMPORTS EXISTENTES =====

from api.job_status import register_job_api  # noqa: E402
from services.workflow_manager import WorkflowManager  # noqa: E402

# ===== ADICIONAR APÓS CRIAR O APP FLASK =====

# Seu código existente:
# app = Flask(__name__)
# CORS(app)

# === NOVO: Registrar API de Jobs ===
register_job_api(app)
logger.info("✅ API de Jobs Assíncronos registrada")

# === NOVO: Configurar agendamentos (apenas se Beat estiver habilitado) ===

if os.getenv("ENABLE_CELERY_BEAT", "false").lower() == "true":
    try:
        workflow_manager = WorkflowManager()
        workflow_manager.configurar_agendamentos()
        logger.info("✅ Agendamentos Celery Beat configurados")
    except Exception as e:
        logger.warning(f"⚠️  Celery Beat não configurado: {e}")

# ===== ADICIONAR ENDPOINT DE TESTE =====


@app.route("/api/test-job", methods=["POST"])
def test_job_endpoint():
    """
    Endpoint de teste para disparar um job simples

    POST /api/test-job
    {
        "empresa_id": "TEST001",
        "mes": 2,
        "ano": 2026
    }
    """
    try:
        from flask import jsonify, request
        from infra.tasks import processar_folha_pagamento

        data = request.get_json() or {}
        empresa_id = data.get("empresa_id", "TEST001")
        mes = data.get("mes", datetime.now().month)
        ano = data.get("ano", datetime.now().year)

        # Dispara job de teste com dados fictícios
        result = processar_folha_pagamento.apply_async(
            kwargs={
                "empresa_id": empresa_id,
                "mes": mes,
                "ano": ano,
                "funcionarios": [
                    {
                        "id": "FUNC001",
                        "nome": "João Silva (TESTE)",
                        "salario_base": "3000.00",
                        "descontos": {},
                        "beneficios": {},
                    }
                ],
            }
        )

        return (
            jsonify(
                {
                    "success": True,
                    "message": "Job de teste disparado com sucesso!",
                    "task_id": result.id,
                    "status_url": f"/api/jobs/{result.id}",
                    "empresa_id": empresa_id,
                    "periodo": f"{mes}/{ano}",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Erro ao disparar job de teste: {e}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                }
            ),
            500,
        )


# ===== ADICIONAR ENDPOINT DE HEALTH CHECK PARA WORKERS =====


@app.route("/api/health/workers", methods=["GET"])
def health_workers():
    """
    Verifica se workers Celery estão ativos

    GET /api/health/workers
    """
    try:
        from flask import jsonify
        from infra.worker import celery_app

        # Verifica workers ativos
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        stats = inspect.stats()

        if not active_workers:
            return (
                jsonify(
                    {
                        "status": "unhealthy",
                        "workers_active": 0,
                        "message": "Nenhum worker ativo",
                    }
                ),
                503,
            )

        return (
            jsonify(
                {
                    "status": "healthy",
                    "workers_active": len(active_workers),
                    "workers": list(active_workers.keys()),
                    "stats": stats,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao verificar workers: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": str(e),
                }
            ),
            500,
        )


# ===== FIM DA INTEGRAÇÃO =====

print("""
╔══════════════════════════════════════════════════════════════╗
║  ✅ CAMADA DE JOBS ASSÍNCRONOS INTEGRADA COM SUCESSO!        ║
╚══════════════════════════════════════════════════════════════╝

📊 Endpoints Disponíveis:
   - GET  /api/jobs/<task_id>          - Status do job
   - GET  /api/jobs/<task_id>/progress - Progresso detalhado
   - GET  /api/jobs/<task_id>/logs     - Logs de execução
   - POST /api/jobs/<task_id>/cancel   - Cancelar job
   - GET  /api/jobs/active             - Jobs ativos
   - POST /api/jobs/trigger            - Disparar workflow
   - GET  /api/jobs/schedules          - Lista agendamentos
   - POST /api/test-job                - Teste rápido
   - GET  /api/health/workers          - Health check workers

🚀 Para Iniciar:
   1. docker-compose up -d
   2. Acesse: http://localhost:5000/api/jobs/schedules
   3. Dispare teste: POST http://localhost:5000/api/test-job

📚 Documentação: README_JOBS_ASSINCRONOS.md
""")
