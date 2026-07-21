"""
API de Status de Jobs - Endpoints para Acompanhamento
Fornece endpoints REST para consulta de progresso de jobs assíncronos

Endpoints:
- GET /api/jobs/<task_id> - Status do job
- GET /api/jobs/<task_id>/progress - Histórico de progresso
- GET /api/jobs/<task_id>/logs - Logs do job
- POST /api/jobs/<task_id>/cancel - Cancela job
- GET /api/jobs/active - Lista jobs ativos
- POST /api/webhooks/job-status - Webhook de notificação
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

try:
    from infra.job_state import JobStateManager, JobStatus
except ImportError:
    from contabil_agente.infra.job_state import JobStateManager, JobStatus

try:
    from services.workflow_manager import WorkflowManager
except ImportError:
    from contabil_agente.services.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)

# Blueprint da API
job_status_bp = Blueprint("job_status", __name__, url_prefix="/api/jobs")


@job_status_bp.route("/<task_id>", methods=["GET"])
def get_job_status(task_id: str) -> tuple:
    """
    Retorna status atual de um job

    GET /api/jobs/<task_id>

    Response:
    {
        "task_id": "abc123",
        "status": "PROCESSING",
        "progress": 45,
        "message": "Processando...",
        "created_at": "2026-02-03T10:00:00",
        "updated_at": "2026-02-03T10:05:00"
    }
    """
    try:
        state_manager = JobStateManager()
        state = state_manager.get_state(task_id)

        if not state:
            return (
                jsonify(
                    {
                        "error": "Job não encontrado",
                        "task_id": task_id,
                    }
                ),
                404,
            )

        return jsonify(state), 200

    except Exception as e:
        logger.error(f"Erro ao buscar status do job {task_id}: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao buscar status",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/<task_id>/progress", methods=["GET"])
def get_job_progress(task_id: str) -> tuple:
    """
    Retorna histórico de progresso do job

    GET /api/jobs/<task_id>/progress

    Response:
    {
        "task_id": "abc123",
        "progress_history": [
            {
                "timestamp": "2026-02-03T10:00:00",
                "status": "PENDING",
                "progress": 0,
                "message": "Job criado"
            },
            ...
        ]
    }
    """
    try:
        state_manager = JobStateManager()
        progress_history = state_manager.get_progress_history(task_id)

        return (
            jsonify(
                {
                    "task_id": task_id,
                    "total_events": len(progress_history),
                    "progress_history": progress_history,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao buscar progresso do job {task_id}: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao buscar progresso",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/<task_id>/logs", methods=["GET"])
def get_job_logs(task_id: str) -> tuple:
    """
    Retorna logs do job

    GET /api/jobs/<task_id>/logs

    Response:
    {
        "task_id": "abc123",
        "logs": [
            {
                "timestamp": "2026-02-03T10:00:00",
                "level": "INFO",
                "message": "Iniciando processamento"
            },
            ...
        ]
    }
    """
    try:
        state_manager = JobStateManager()
        logs = state_manager.get_logs(task_id)

        return (
            jsonify(
                {
                    "task_id": task_id,
                    "total_logs": len(logs),
                    "logs": logs,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao buscar logs do job {task_id}: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao buscar logs",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/<task_id>/cancel", methods=["POST"])
def cancel_job(task_id: str) -> tuple:
    """
    Cancela um job

    POST /api/jobs/<task_id>/cancel

    Response:
    {
        "task_id": "abc123",
        "cancelled": true,
        "message": "Job cancelado com sucesso"
    }
    """
    try:
        state_manager = JobStateManager()
        cancelled = state_manager.cancel_job(task_id)

        if cancelled:
            return (
                jsonify(
                    {
                        "task_id": task_id,
                        "cancelled": True,
                        "message": "Job cancelado com sucesso",
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "task_id": task_id,
                        "cancelled": False,
                        "message": "Job não pode ser cancelado (já finalizado ou não encontrado)",
                    }
                ),
                400,
            )

    except Exception as e:
        logger.error(f"Erro ao cancelar job {task_id}: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao cancelar job",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/active", methods=["GET"])
def list_active_jobs() -> tuple:
    """
    Lista jobs ativos/em execução

    GET /api/jobs/active

    Query params:
    - status: Filtrar por status (PENDING, PROCESSING, etc.)
    - limit: Limite de resultados (padrão: 50)

    Response:
    {
        "total": 10,
        "jobs": [...]
    }
    """
    try:
        # Parâmetros de query
        status_filter = request.args.get("status")
        limit = int(request.args.get("limit", 50))

        state_manager = JobStateManager()

        # Busca jobs (Redis ou memória com fallback)
        jobs = state_manager.list_jobs(status_filter=status_filter, limit=limit)

        return (
            jsonify(
                {
                    "total": len(jobs),
                    "limit": limit,
                    "status_filter": status_filter,
                    "jobs": jobs,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao listar jobs ativos: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao listar jobs",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/trigger", methods=["POST"])
def trigger_workflow() -> tuple:
    """
    Dispara workflow manualmente

    POST /api/jobs/trigger

    Body:
    {
        "workflow_name": "processar_folha",
        "args": [...],
        "kwargs": {...},
        "user_id": "user123"
    }

    Response:
    {
        "task_id": "abc123",
        "workflow_name": "processar_folha",
        "status": "PENDING",
        "message": "Workflow disparado com sucesso"
    }
    """
    try:
        data = request.get_json()

        if not data or "workflow_name" not in data:
            return (
                jsonify(
                    {
                        "error": "workflow_name é obrigatório",
                    }
                ),
                400,
            )

        workflow_name = data["workflow_name"]
        args = tuple(data.get("args", []))
        kwargs = data.get("kwargs", {})
        user_id = data.get("user_id")

        # Dispara workflow
        workflow_manager = WorkflowManager()
        task_id = workflow_manager.executar_workflow_agora(
            task_name=workflow_name,
            args=args,
            kwargs=kwargs,
            user_id=user_id,
        )

        return (
            jsonify(
                {
                    "task_id": task_id,
                    "workflow_name": workflow_name,
                    "status": JobStatus.PENDING,
                    "message": "Workflow disparado com sucesso",
                    "triggered_at": datetime.now().isoformat(),
                }
            ),
            201,
        )

    except ValueError as e:
        return (
            jsonify(
                {
                    "error": "Workflow inválido",
                    "details": str(e),
                }
            ),
            400,
        )
    except Exception as e:
        logger.error(f"Erro ao disparar workflow: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao disparar workflow",
                    "details": str(e),
                }
            ),
            500,
        )


@job_status_bp.route("/schedules", methods=["GET"])
def list_schedules() -> tuple:
    """
    Lista agendamentos ativos

    GET /api/jobs/schedules

    Response:
    {
        "total": 4,
        "schedules": [
            {
                "nome": "folha-mensal",
                "task": "infra.workflows.executar_folha_mensal",
                "schedule": "crontab(...)",
                ...
            }
        ]
    }
    """
    try:
        workflow_manager = WorkflowManager()
        agendamentos = workflow_manager.listar_agendamentos_ativos()

        return (
            jsonify(
                {
                    "total": len(agendamentos),
                    "schedules": agendamentos,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao listar agendamentos: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao listar agendamentos",
                    "details": str(e),
                }
            ),
            500,
        )


# === WEBHOOKS ===


@job_status_bp.route("/webhooks/notify", methods=["POST"])
def webhook_job_notification() -> tuple:
    """
    Webhook para notificações externas de status de job
    Pode ser chamado por sistemas externos ou pelo próprio worker

    POST /api/jobs/webhooks/notify

    Body:
    {
        "task_id": "abc123",
        "event": "job_completed",
        "data": {...}
    }
    """
    try:
        data = request.get_json()

        if not data or "task_id" not in data or "event" not in data:
            return (
                jsonify(
                    {
                        "error": "task_id e event são obrigatórios",
                    }
                ),
                400,
            )

        task_id = data["task_id"]
        event = data["event"]
        data.get("data", {})

        # Processa evento
        logger.info(f"📬 Webhook recebido: {event} para job {task_id}")

        # Aqui você pode adicionar lógica customizada:
        # - Enviar email
        # - Notificar via Slack/Teams
        # - Atualizar banco de dados externo
        # - Disparar outros workflows

        return (
            jsonify(
                {
                    "received": True,
                    "task_id": task_id,
                    "event": event,
                    "processed_at": datetime.now().isoformat(),
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        return (
            jsonify(
                {
                    "error": "Erro interno ao processar webhook",
                    "details": str(e),
                }
            ),
            500,
        )


def register_job_api(app) -> None:
    """
    Registra blueprint da API de jobs no app Flask

    Args:
        app: Instância do Flask
    """
    app.register_blueprint(job_status_bp)
    logger.info("✅ API de Jobs registrada em /api/jobs")
