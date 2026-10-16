from flask import Flask  # type: ignore[reportMissingImports]

app = Flask(__name__)


"""
Guia de Integração - Camada de Jobs Assíncronos
================================================

Este guia mostra como integrar a infraestrutura de jobs no seu app.py

1. IMPORTAR A API DE JOBS
"""

# No seu app.py, adicione após as outras importações:
from api.job_status import register_job_api  # noqa: E402

"""
2. REGISTRAR A API NO FLASK
"""

# Após criar o app Flask, adicione:
# app = Flask(__name__)
# CORS(app)

# Registra API de Jobs
register_job_api(app)

# Configura agendamentos automáticos (apenas se estiver rodando Beat)
# if os.getenv("CELERY_BEAT_ENABLED", "false").lower() == "true":
#     workflow_manager = WorkflowManager()
#     workflow_manager.configurar_agendamentos()

"""
3. EXEMPLO DE USO NO CHAT: DISPARAR JOB ASSÍNCRONO
"""


# Quando o usuário pedir para processar folha no chat:
def processar_folha_chat(empresa_id: str, mes: int, ano: int, funcionarios: list):
    """
    Dispara job de folha de forma assíncrona
    Retorna job_id imediatamente sem bloquear o chat
    """
    from infra.tasks import processar_folha_pagamento

    # Dispara job
    result = processar_folha_pagamento.apply_async(
        kwargs={
            "empresa_id": empresa_id,
            "mes": mes,
            "ano": ano,
            "funcionarios": funcionarios,
        }
    )

    task_id = result.id

    # Retorna resposta ao usuário imediatamente
    return {
        "message": "Processamento de folha iniciado!",
        "task_id": task_id,
        "status_url": f"/api/jobs/{task_id}",
        "instrucoes": "Acompanhe o progresso acessando a URL acima",
    }


"""
4. EXEMPLO: CONSULTAR STATUS DE JOB
"""

# O usuário pode consultar o status via API:
# GET /api/jobs/<task_id>


# Ou você pode criar uma função no chat:
def verificar_status_job(task_id: str):
    """Verifica status de um job em andamento"""
    from infra.job_state import JobStateManager

    state_manager = JobStateManager()
    state = state_manager.get_state(task_id)

    if not state:
        return "Job não encontrado"

    status = state["status"]
    progress = state.get("progress", 0)
    message = state.get("message", "")

    return f"""
    📊 Status do Job: {status}
    📈 Progresso: {progress}%
    💬 Mensagem: {message}
    """


"""
5. EXEMPLO: WORKFLOW COMPLETO (FOLHA → SPED)
"""


def workflow_mensal_completo(empresa_id: str, mes: int, ano: int):
    """
    Executa workflow completo:
    1. Processa folha
    2. Gera SPED
    3. Envia notificações
    """
    from celery import chain
    from infra.tasks import gerar_sped, processar_folha_pagamento

    # Cria cadeia de tasks
    workflow = chain(
        processar_folha_pagamento.s(
            empresa_id=empresa_id,
            mes=mes,
            ano=ano,
            funcionarios=[],  # Buscar do banco
        ),
        gerar_sped.s(
            empresa_id=empresa_id,
            tipo_sped="CONTABIL",
            periodo_inicio=f"{ano}-{mes:02d}-01",
            periodo_fim=f"{ano}-{mes:02d}-28",
            dados={},
        ),
    )

    # Dispara workflow
    result = workflow.apply_async()

    return {
        "message": "Workflow mensal iniciado!",
        "workflow_id": result.id,
    }


"""
6. ROTAS FLASK PARA O CHAT DISPARAR JOBS
"""

# Adicione estas rotas ao seu app.py:
from flask import Blueprint, jsonify, request  # noqa: E402

chat_jobs_bp = Blueprint("chat_jobs", __name__, url_prefix="/api/chat")


@chat_jobs_bp.route("/processar-folha", methods=["POST"])
def api_processar_folha():
    """
    POST /api/chat/processar-folha

    Body:
    {
        "empresa_id": "EMP001",
        "mes": 2,
        "ano": 2026,
        "funcionarios": [...]
    }
    """
    data = request.get_json()

    empresa_id = data.get("empresa_id")
    mes = data.get("mes")
    ano = data.get("ano")
    funcionarios = data.get("funcionarios", [])

    # Dispara job
    result = processar_folha_chat(empresa_id, mes, ano, funcionarios)

    return jsonify(result), 202  # 202 = Accepted


@chat_jobs_bp.route("/status/<task_id>", methods=["GET"])
def api_status_job(task_id: str):
    """GET /api/chat/status/<task_id>"""
    status = verificar_status_job(task_id)
    return jsonify({"status": status}), 200


# Registra blueprint
# app.register_blueprint(chat_jobs_bp)

"""
7. COMANDOS DOCKER
"""

# Para iniciar todos os serviços:
# docker-compose up -d

# Para ver logs do worker:
# docker-compose logs -f worker

# Para ver logs do beat (agendador):
# docker-compose logs -f beat

# Para escalar workers (múltiplos workers):
# docker-compose up -d --scale worker=3

"""
8. MONITORAMENTO DE JOBS
"""

# Flower - Dashboard web para Celery
# Adicione ao docker-compose.yml:
"""
  flower:
    build: .
    container_name: agente_contabil_flower
    command: celery -A infra.worker flower --port=5555
    ports:
      - "5555:5555"
    depends_on:
      - redis
      - worker
    environment:
      - CELERY_BROKER_URL=redis://agente_contabil_redis:6379/0
"""

# Acesse: http://localhost:5555

"""
9. TESTES LOCAIS (SEM DOCKER)
"""

# Terminal 1 - Redis
# redis-server

# Terminal 2 - Worker
# cd contabil_agente
# celery -A infra.worker worker --loglevel=info

# Terminal 3 - Beat (agendador)
# celery -A infra.worker beat --loglevel=info

# Terminal 4 - Flask App
# python app.py

"""
10. EXEMPLO COMPLETO DE INTEGRAÇÃO NO APP.PY
"""

# app.py completo com jobs:
"""
from flask import Flask
from flask_cors import CORS
from api.job_status import register_job_api
from services.workflow_manager import WorkflowManager

app = Flask(__name__)
CORS(app)

# Registra API de Jobs
register_job_api(app)

# Configura agendamentos (apenas no Beat)
import os
if os.getenv("ENABLE_BEAT", "false").lower() == "true":
    workflow_manager = WorkflowManager()
    workflow_manager.configurar_agendamentos()

# Suas outras rotas...
from routes.chat_refactored import chat_refactored_bp
app.register_blueprint(chat_refactored_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
"""

"""
11. SEGURANÇA E BOAS PRÁTICAS
"""

# ✅ SEMPRE usar variáveis de ambiente para senhas
# ✅ Redis com autenticação em produção
# ✅ Rate limiting em endpoints de trigger
# ✅ Validação de permissões antes de disparar jobs
# ✅ Logs detalhados com GerenciadorEvidencias
# ✅ TTL em resultados para evitar acúmulo no Redis
# ✅ Monitoramento de memória e CPU dos workers

"""
12. TROUBLESHOOTING
"""

# Job não inicia:
# - Verificar se Redis está rodando
# - Verificar se worker está rodando
# - Ver logs: docker-compose logs worker

# Job trava:
# - Aumentar task_time_limit no worker.py
# - Verificar memória disponível
# - Ver logs de exceções

# Beat não agenda:
# - Verificar se beat está rodando
# - Ver logs: docker-compose logs beat
# - Testar crontab: https://crontab.guru/

"""
FIM DO GUIA DE INTEGRAÇÃO
==========================

Próximos passos:
1. Atualizar app.py com a integração
2. Instalar dependências: pip install -r requirements.txt
3. Iniciar com Docker: docker-compose up -d
4. Testar endpoint: GET /api/jobs/schedules
5. Disparar job de teste: POST /api/jobs/trigger

Documentação adicional:
- Celery: https://docs.celeryq.dev/
- Redis: https://redis.io/docs/
- Flower: https://flower.readthedocs.io/
"""
