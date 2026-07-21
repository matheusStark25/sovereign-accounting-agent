"""
Exemplo de integração OPCIONAL dos middleware de segurança.
Este arquivo mostra como habilitar segurança SEM modificar rotas existentes.

Para usar:
1. Copie .env.production.example para .env e configure
2. No app.py, importe: from config.security_config import configure_security
3. Após criar app: configure_security(app, enable_all=False)  # Habilita apenas alguns
"""

import logging
import os

from flask import Flask  # type: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


def configure_security(
    app: Flask,
    enable_all: bool = False,
    enable_auth: bool = False,
    enable_rate_limit: bool = False,
    enable_validation: bool = False,
    enable_security_headers: bool = True,  # Safe to enable sempre
    enable_metrics: bool = False,
    enable_lgpd: bool = False,
):
    """
    Configura camadas de segurança de forma modular.

    Args:
        app: Instância Flask
        enable_all: Habilita todas features (dev/staging)
        enable_auth: API key authentication
        enable_rate_limit: Rate limiting
        enable_validation: Input validation
        enable_security_headers: Security headers (CORS, CSP, etc)
        enable_metrics: Prometheus metrics
        enable_lgpd: LGPD compliance features

    Uso:
        # Modo conservador (apenas headers):
        configure_security(app)

        # Modo progressivo (adiciona rate limiting):
        configure_security(app, enable_rate_limit=True)

        # Modo completo:
        configure_security(app, enable_all=True)
    """

    if enable_all:
        enable_auth = True
        enable_rate_limit = True
        enable_validation = True
        enable_security_headers = True
        enable_metrics = True
        enable_lgpd = True

    # 1. Security Headers (sempre seguro habilitar)
    if enable_security_headers:
        try:
            from middleware.security_headers import SecurityHeaders

            allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
            SecurityHeaders.setup_app(app, allowed_origins)

            logger.info("✅ Security headers habilitados (CORS, CSP, HSTS)")
        except Exception as e:
            logger.error(f"❌ Erro ao configurar security headers: {e}")

    # 2. Metrics (não invasivo, apenas coleta)
    if enable_metrics:
        try:
            from routes.metrics import metrics_bp

            # Registra blueprint de métricas
            app.register_blueprint(metrics_bp, url_prefix="/api")

            logger.info("✅ Métricas Prometheus habilitadas em /api/metrics")
        except Exception as e:
            logger.error(f"❌ Erro ao configurar métricas: {e}")

    # 3. Rate Limiting (pode afetar performance sob carga)
    if enable_rate_limit:
        try:
            from middleware.rate_limiter import get_rate_limiter

            # Instancia rate limiter
            get_rate_limiter()

            # Opcional: configurar via before_request
            @app.before_request
            def check_rate_limit():
                # Aplica apenas em rotas específicas se quiser
                # if request.endpoint and 'chat' in request.endpoint:
                #     ...
                pass

            logger.info("✅ Rate limiter configurado (use @rate_limit nos endpoints)")
        except Exception as e:
            logger.error(f"❌ Erro ao configurar rate limiter: {e}")

    # 4. Authentication (REQUER modificação de rotas)
    if enable_auth:
        logger.warning(
            "⚠️  Auth habilitado: adicione @require_api_key nas rotas protegidas"
        )
        logger.info("    Exemplo: from middleware.auth import require_api_key")

    # 5. Validation (REQUER modificação de rotas)
    if enable_validation:
        logger.warning(
            "⚠️  Validation habilitado: use @validate_chat_input nas rotas de chat"
        )
        logger.info(
            "    Exemplo: from middleware.validators import validate_chat_input"
        )

    # 6. LGPD (passivo, não afeta rotas)
    if enable_lgpd:
        try:
            from middleware.lgpd import LGPDLogger

            # Configura logger LGPD
            LGPDLogger("logs/lgpd_events.log")

            logger.info("✅ LGPD compliance habilitado (PIIAnonymizer, ConsentManager)")
        except Exception as e:
            logger.error(f"❌ Erro ao configurar LGPD: {e}")

    logger.info("🔒 Configuração de segurança concluída")
    return app


def get_middleware_status() -> dict:
    """Retorna status de quais middleware estão disponíveis."""
    status = {}

    try:
        import middleware.auth  # noqa: F401

        status["auth"] = True
    except Exception:
        status["auth"] = False

    try:
        import middleware.rate_limiter  # noqa: F401

        status["rate_limit"] = True
    except Exception:
        status["rate_limit"] = False

    try:
        from middleware.validators import validate_chat_input  # noqa: F401

        status["validation"] = True
    except Exception:
        status["validation"] = False

    try:
        from middleware.security_headers import SecurityHeaders  # noqa: F401

        status["security_headers"] = True
    except Exception:
        status["security_headers"] = False

    try:
        from middleware.observability import get_metrics_collector  # noqa: F401

        status["metrics"] = True
    except Exception:
        status["metrics"] = False

    try:
        from middleware.lgpd import PIIAnonymizer  # noqa: F401

        status["lgpd"] = True
    except Exception:
        status["lgpd"] = False

    try:
        import middleware.resilience  # noqa: F401

        status["resilience"] = True
    except Exception:
        status["resilience"] = False

    return status
