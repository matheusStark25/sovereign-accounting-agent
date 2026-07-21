"""
Rotas Multi-Tenant com Autenticação
"""

import logging
import uuid

from flask import Blueprint, jsonify, request
from middleware.auth import get_current_empresa, require_api_key
from services.chat_service import ChatService
from services.session_service import SessionService

logger = logging.getLogger(__name__)

chat_multi_tenant_bp = Blueprint("chat_multi_tenant", __name__, url_prefix="/api/v2")


@chat_multi_tenant_bp.route("/empresas", methods=["GET"])
def listar_empresas():
    """Lista empresas disponíveis (sem autenticação - público)"""
    from config_empresas import listar_empresas

    return jsonify(listar_empresas())


@chat_multi_tenant_bp.route("/chat/<empresa_id>", methods=["POST"])
@require_api_key
def chat_empresa(empresa_id):
    """
    Endpoint de chat multi-tenant
    Requer autenticação por API key
    """
    try:
        empresa_config = get_current_empresa()

        # Validar payload
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Campo 'message' obrigatório"}), 400

        user_message = data["message"]
        session_id = data.get("session_id") or str(uuid.uuid4())

        logger.info(
            f"[{empresa_config.nome}] Processando mensagem: {user_message[:50]}..."
        )

        # Criar serviços isolados para esta empresa
        chat_service = ChatService(api_key=empresa_config.api_key)

        # Configurar modelo da empresa
        chat_service.model = empresa_config.ai_model
        chat_service.temperature = empresa_config.ai_temperature
        chat_service.max_tokens = empresa_config.max_tokens

        # Processar mensagem
        response = chat_service.process_message(
            session_id=session_id,
            user_message=user_message,
            assistente_nome=empresa_config.assistente_nome,
        )

        # Adicionar metadata da empresa
        response["empresa"] = {
            "id": empresa_config.id,
            "nome": empresa_config.nome,
            "assistente": empresa_config.assistente_nome,
        }

        logger.info(f"[{empresa_config.nome}] Resposta enviada com sucesso")

        return jsonify(response)

    except Exception as e:
        logger.error(f"Erro no chat da empresa {empresa_id}: {e}", exc_info=True)
        return jsonify({"error": "Erro ao processar mensagem", "details": str(e)}), 500


@chat_multi_tenant_bp.route("/health/<empresa_id>", methods=["GET"])
@require_api_key
def health_empresa(empresa_id):
    """Health check específico da empresa"""
    import os

    empresa_config = get_current_empresa()

    checks = {
        "database": os.path.exists(empresa_config.db_path),
        "api_key_configured": bool(empresa_config.api_key),
        "model_configured": bool(empresa_config.ai_model),
        "logo_exists": (
            os.path.exists(empresa_config.logo_path)
            if empresa_config.logo_path
            else None
        ),
    }

    status = (
        "healthy" if all(v for v in checks.values() if v is not None) else "degraded"
    )

    return jsonify(
        {
            "status": status,
            "empresa": empresa_config.nome,
            "assistente": empresa_config.assistente_nome,
            "checks": checks,
        }
    )


@chat_multi_tenant_bp.route("/session/<empresa_id>/<session_id>", methods=["GET"])
@require_api_key
def get_session(empresa_id, session_id):
    """Recupera informações de uma sessão"""
    try:
        empresa_config = get_current_empresa()
        session_service = SessionService(db_path=empresa_config.db_path)

        session_data = session_service.get_session(session_id)

        if not session_data:
            return jsonify({"error": "Sessão não encontrada"}), 404

        return jsonify(
            {
                "session_id": session_id,
                "empresa": empresa_config.nome,
                "messages_count": len(session_data.get("messages", [])),
                "last_activity": session_data.get("last_activity"),
            }
        )

    except Exception as e:
        logger.error(f"Erro ao recuperar sessão: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@chat_multi_tenant_bp.route("/session/<empresa_id>/<session_id>", methods=["DELETE"])
@require_api_key
def delete_session(empresa_id, session_id):
    """Deleta uma sessão"""
    try:
        empresa_config = get_current_empresa()
        session_service = SessionService(db_path=empresa_config.db_path)

        session_service.delete_session(session_id)

        logger.info(f"[{empresa_config.nome}] Sessão {session_id} deletada")

        return jsonify({"message": "Sessão deletada com sucesso"})

    except Exception as e:
        logger.error(f"Erro ao deletar sessão: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@chat_multi_tenant_bp.route("/stats/<empresa_id>", methods=["GET"])
@require_api_key
def get_stats(empresa_id):
    """Estatísticas da empresa"""
    try:
        empresa_config = get_current_empresa()

        # Contar sessões ativas
        import sqlite3
        import time

        with sqlite3.connect(empresa_config.db_path) as conn:
            cursor = conn.cursor()

            # Sessões nas últimas 24h
            cutoff_time = time.time() - (24 * 3600)
            cursor.execute(
                "SELECT COUNT(*) FROM sessions WHERE last_activity > ?", (cutoff_time,)
            )
            sessions_24h = cursor.fetchone()[0]

            # Total de sessões
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]

        return jsonify(
            {
                "empresa": empresa_config.nome,
                "total_sessions": total_sessions,
                "active_24h": sessions_24h,
                "model": empresa_config.ai_model,
                "rate_limit": empresa_config.rate_limit,
            }
        )

    except Exception as e:
        logger.error(f"Erro ao obter stats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
