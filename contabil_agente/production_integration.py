"""
INTEGRAÃÃO COM AGENT_CONTABIL.PY
Adiciona endpoints de monitoramento SEM MODIFICAR cÃ³digo existente
"""

from config_redis import get_redis_manager
from flask import Blueprint, jsonify

from monitoring import get_metrics_collector

# Blueprint para mÃ©tricas (registrar no app principal)
metrics_bp = Blueprint("metrics", __name__)


@metrics_bp.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Endpoint de mÃ©tricas em JSON"""
    collector = get_metrics_collector()
    return jsonify(collector.get_metrics())


@metrics_bp.route("/api/metrics/prometheus", methods=["GET"])
def get_prometheus_metrics():
    """Endpoint de mÃ©tricas formato Prometheus"""
    collector = get_metrics_collector()
    return collector.get_prometheus_metrics(), 200, {"Content-Type": "text/plain"}


@metrics_bp.route("/api/health/detailed", methods=["GET"])
def get_health_detailed():
    """Health check detalhado"""
    collector = get_metrics_collector()
    return jsonify(collector.get_health_status())


@metrics_bp.route("/api/admin/cache/clear", methods=["POST"])
def clear_cache():
    """Limpa cache Redis (requer autenticaÃ§Ã£o)"""
    redis_mgr = get_redis_manager()

    # TODO: Adicionar autenticaÃ§Ã£o JWT aqui
    # if not verify_admin_token(request.headers.get('Authorization')):
    #     return jsonify({'error': 'Unauthorized'}), 401

    if redis_mgr.client:
        try:
            redis_mgr.client.flushdb()
            return jsonify({"status": "success", "message": "Cache limpo"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return jsonify({"status": "error", "message": "Redis nÃ£o disponÃ­vel"}), 503


# ===== INSTRUÃÃES DE USO =====
"""
COMO INTEGRAR COM AGENT_CONTABIL.PY:

1. No agent_contabil.py, adicione estas linhas DEPOIS de criar o app Flask:

    # Importa integraÃ§Ãµes de produÃ§Ã£o (se existir)
    try:
        from production_integration import metrics_bp
        app.register_blueprint(metrics_bp)
        print("â Endpoints de monitoramento registrados")
    except ImportError:
        print("â ï¸ production_integration.py nÃ£o encontrado")

2. Para usar o decorator de monitoramento em funÃ§Ãµes existentes:

    from production_integration import monitor_execution_time

    @app.route('/api/chat', methods=['POST'])
    @monitor_execution_time  # Adiciona essa linha
    def chat_endpoint():
        # ... cÃ³digo existente ...

3. Para usar Redis cache em cÃ¡lculos:

    from config_redis import redis_cache

    @redis_cache(ttl=3600, key_prefix="calculo_inss")
    def _calcular_inss_detalhado(self, salario_base):
        # ... cÃ³digo existente ...

4. Para rate limiting com Redis:

    from config_redis import get_redis_manager, RedisRateLimiter

    redis_mgr = get_redis_manager()
    limiter = RedisRateLimiter(redis_mgr)

    # Em cada endpoint:
    client_ip = request.remote_addr
    if not limiter.is_allowed(client_ip, limit=100, window=60):
        return jsonify({'error': 'Rate limit exceeded'}), 429

ENDPOINTS NOVOS DISPONÃVEIS:

GET  /api/metrics              - MÃ©tricas em JSON
GET  /api/metrics/prometheus   - MÃ©tricas formato Prometheus
GET  /api/health/detailed      - Status de saÃºde detalhado
POST /api/admin/cache/clear    - Limpa cache Redis

EXECUTAR TESTES:

    cd contabil_agente
    pytest test_completo.py -v

MODO PRODUÃÃO:

    # Linux/Mac:
    bash start_production.sh

    # Windows:
    powershell -ExecutionPolicy Bypass -File start_production.ps1
"""

if __name__ == "__main__":
    print(__doc__)
