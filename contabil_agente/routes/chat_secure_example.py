"""
Exemplo de integração dos middleware em rotas existentes.
Este arquivo NÃO substitui routes/chat_refactored.py.
É apenas uma DEMONSTRAÇÃO de como adicionar segurança.

Para usar de verdade, copie os decoradores para routes/chat_refactored.py
"""

import logging

from flask import Blueprint, jsonify, request

# Importa middleware (OPCIONAL - só se quiser habilitar)
try:
    from middleware.auth import require_api_key
    from middleware.observability import StructuredLogger, track_request_metrics
    from middleware.rate_limiter import rate_limit
    from middleware.validators import validate_chat_input

    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    logging.warning("Middleware de segurança não disponível")

# Blueprint de exemplo
chat_secure_bp = Blueprint("chat_secure", __name__)
logger = logging.getLogger(__name__)

if SECURITY_AVAILABLE:
    structured_logger = StructuredLogger("chat_secure")
else:
    structured_logger = None


def processar_chat_com_seguranca():
    """
    Exemplo de endpoint de chat COM todas camadas de segurança.

    Camadas aplicadas:
    1. Rate limiting (per IP)
    2. Input validation
    3. Metrics tracking
    4. Authentication (opcional)
    """
    try:
        data = request.get_json()
        mensagem = data.get("mensagem", "").strip()
        session_id = data.get("session_id")

        # Log estruturado
        if structured_logger:
            structured_logger.info(
                "Chat request recebido",
                mensagem_length=len(mensagem),
                has_session=session_id is not None,
            )

        # Aqui entraria a lógica real do chat
        # Por exemplo, chamar services.chat_service.process_message()

        resposta_exemplo = {
            "resposta": "Processado com segurança!",
            "session_id": session_id or "new_session",
            "message_count": 1,
            "security_enabled": SECURITY_AVAILABLE,
        }

        return jsonify(resposta_exemplo), 200

    except Exception as e:
        logger.error(f"Erro ao processar chat: {e}")
        return jsonify({"erro": "Erro interno", "detalhes": str(e)}), 500


# Versão 1: COM autenticação (requer API key)
if SECURITY_AVAILABLE:

    @chat_secure_bp.route("/chat_authenticated", methods=["POST"])
    @require_api_key
    @rate_limit("per_api_key")
    @validate_chat_input
    @track_request_metrics
    def chat_authenticated():
        """Chat que requer API key."""
        return processar_chat_com_seguranca()


# Versão 2: SEM autenticação (apenas rate limit + validação)
if SECURITY_AVAILABLE:

    @chat_secure_bp.route("/chat_public", methods=["POST"])
    @rate_limit("per_ip")
    @validate_chat_input
    @track_request_metrics
    def chat_public():
        """Chat público com rate limit."""
        return processar_chat_com_seguranca()

else:

    @chat_secure_bp.route("/chat_public", methods=["POST"])
    def chat_public_fallback():
        """Fallback sem middleware."""
        return processar_chat_com_seguranca()


# Versão 3: Totalmente SEM segurança (para comparação)
@chat_secure_bp.route("/chat_insecure", methods=["POST"])
def chat_insecure():
    """
    Endpoint SEM nenhuma proteção (apenas para testes).
    NÃO USE EM PRODUÇÃO!
    """
    return processar_chat_com_seguranca()


# Helper para verificar status da segurança
@chat_secure_bp.route("/security_status", methods=["GET"])
def security_status():
    """Retorna quais módulos de segurança estão ativos."""
    from config.security_config import get_middleware_status

    status = get_middleware_status()

    return (
        jsonify(
            {
                "security_available": SECURITY_AVAILABLE,
                "middleware_status": status,
                "recommendations": [
                    "Use /chat_authenticated para máxima segurança (requer API key)",
                    "Use /chat_public para uso público com proteções básicas",
                    "NUNCA use /chat_insecure em produção",
                ],
            }
        ),
        200,
    )


"""
COMO INTEGRAR NO APP.PY EXISTENTE:

Opção 1 - Habilitar blueprint de exemplo (não recomendado para produção):
    from routes.chat_secure_example import chat_secure_bp
    app.register_blueprint(chat_secure_bp, url_prefix='/api/secure')

Opção 2 - Adicionar middleware à rota EXISTENTE (recomendado):

    No arquivo routes/chat_refactored.py, adicione:

    from middleware.rate_limiter import rate_limit
    from middleware.validators import validate_chat_input

    @chat_refactored_bp.route('/processar_chat', methods=['POST'])
    @rate_limit('per_ip')  # <-- ADICIONE ISSO
    @validate_chat_input   # <-- E ISSO
    def processar_chat_refactored():
        # Código existente não muda!
        ...

Opção 3 - Habilitar globalmente no app.py (mais simples):

    from config.security_config import configure_security

    app = Flask(__name__)

    # Habilita security headers + métricas (não afeta rotas):
    configure_security(app, enable_security_headers=True, enable_metrics=True)

    # Para adicionar rate limiting e validação, ainda precisa dos decoradores
"""
