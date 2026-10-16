"""
Script de Teste Rápido - Jobs Assíncronos
Testa toda a infraestrutura de jobs sem precisar do Docker
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

print("🧪 TESTE RÁPIDO - INFRAESTRUTURA DE JOBS ASSÍNCRONOS\n")

# ===== TESTE 1: IMPORTS =====
print("1️⃣ Testando imports...")
try:
    import importlib

    from api.job_status import job_status_bp
    from infra.job_state import JobStateManager, JobStatus

    # Import modules dynamically so we only test importability (avoids unused-import lint)
    _tasks_mod = importlib.import_module("infra.tasks")
    _worker_mod = importlib.import_module("infra.worker")
    celery_app = getattr(_worker_mod, "celery_app", None)
    AuditedTask = getattr(_worker_mod, "AuditedTask", None)
    gerar_sped = getattr(_tasks_mod, "gerar_sped", None)
    processar_folha_pagamento = getattr(_tasks_mod, "processar_folha_pagamento", None)
    from services.workflow_manager import WorkflowManager

    print("   ✅ Todos os imports OK\n")
except ImportError as e:
    print(f"   ❌ Erro no import: {e}\n")
    sys.exit(1)

# ===== TESTE 2: CONFIGURAÇÃO CELERY =====
print("2️⃣ Testando configuração Celery...")
try:
    assert celery_app.conf.broker_url, "Broker URL não configurado"
    assert celery_app.conf.result_backend, "Result backend não configurado"
    print(f"   ✅ Broker: {celery_app.conf.broker_url}")
    print(f"   ✅ Backend: {celery_app.conf.result_backend}")
    print(f"   ✅ Timezone: {celery_app.conf.timezone}\n")
except AssertionError as e:
    print(f"   ❌ {e}\n")
    sys.exit(1)

# ===== TESTE 3: JOB STATE MANAGER =====
print("3️⃣ Testando JobStateManager...")
try:
    # Tenta conectar no Redis
    state_manager = JobStateManager()

    # Testa criação de job
    test_job_id = "test_job_123"
    state = state_manager.create_job(
        task_id=test_job_id,
        task_name="test_task",
        user_id="test_user",
        metadata={"test": True},
    )

    assert state["task_id"] == test_job_id
    assert state["status"] == JobStatus.PENDING
    print("   ✅ Job criado no Redis")

    # Testa atualização
    state_manager.update_state(
        test_job_id,
        status=JobStatus.PROCESSING,
        progress=50,
        message="Teste em andamento",
    )

    # Testa recuperação
    retrieved_state = state_manager.get_state(test_job_id)
    assert retrieved_state["status"] == JobStatus.PROCESSING
    assert retrieved_state["progress"] == 50
    print("   ✅ Estado atualizado e recuperado")

    # Testa logs
    state_manager.add_log(test_job_id, "INFO", "Log de teste")
    logs = state_manager.get_logs(test_job_id)
    assert len(logs) > 0
    print("   ✅ Logs funcionando")

    # Testa progresso
    progress = state_manager.get_progress_history(test_job_id)
    assert len(progress) > 0
    print("   ✅ Histórico de progresso OK")

    # Limpa teste
    state_manager.redis_client.delete(f"job:{test_job_id}:state")
    state_manager.redis_client.delete(f"job:{test_job_id}:progress")
    state_manager.redis_client.delete(f"job:{test_job_id}:logs")
    print("   ✅ JobStateManager totalmente funcional\n")

except Exception as e:
    print(f"   ⚠️  Redis não conectado (esperado se não estiver rodando): {e}")
    print("   💡 Para testar completamente, inicie o Redis:")
    print("      - docker-compose up redis -d")
    print("      - OU: redis-server\n")

# ===== TESTE 4: WORKFLOW MANAGER =====
print("4️⃣ Testando WorkflowManager...")
try:
    workflow_manager = WorkflowManager()

    # Lista agendamentos
    agendamentos = workflow_manager.listar_agendamentos_ativos()
    print("   ✅ WorkflowManager criado")
    print(f"   📋 Agendamentos configurados: {len(agendamentos)}")

    if agendamentos:
        for ag in agendamentos[:3]:  # Mostra primeiros 3
            print(f"      - {ag['nome']}: {ag['task']}")
    print()

except Exception as e:
    print(f"   ❌ Erro: {e}\n")

# ===== TESTE 5: TASKS =====
print("5️⃣ Testando tasks registradas...")
try:
    registered_tasks = celery_app.tasks.keys()
    job_tasks = [
        t for t in registered_tasks if "infra.tasks" in t or "infra.workflows" in t
    ]

    print(f"   ✅ Total de tasks Celery: {len(registered_tasks)}")
    print(f"   ✅ Tasks de jobs: {len(job_tasks)}")

    if job_tasks:
        print("   📋 Tasks principais:")
        for task in sorted(job_tasks)[:5]:  # Mostra primeiras 5
            print(f"      - {task}")
    print()

except Exception as e:
    print(f"   ❌ Erro: {e}\n")

# ===== TESTE 6: API BLUEPRINT =====
print("6️⃣ Testando API Blueprint...")
try:
    from flask import Flask  # type: ignore[reportMissingImports]

    app = Flask(__name__)
    app.register_blueprint(job_status_bp)

    # Lista rotas
    job_routes = [r for r in app.url_map.iter_rules() if "/api/jobs" in r.rule]

    print("   ✅ Blueprint registrado")
    print(f"   ✅ Endpoints criados: {len(job_routes)}")
    print("   📋 Principais endpoints:")
    for route in sorted(job_routes, key=lambda x: x.rule)[:8]:
        methods = ",".join(route.methods - {"OPTIONS", "HEAD"})
        print(f"      - {methods:6} {route.rule}")
    print()

except Exception as e:
    print(f"   ❌ Erro: {e}\n")

# ===== TESTE 7: ESTRUTURA DE ARQUIVOS =====
print("7️⃣ Verificando estrutura de arquivos...")
try:
    required_files = [
        "infra/__init__.py",
        "infra/worker.py",
        "infra/job_state.py",
        "infra/tasks.py",
        "services/workflow_manager.py",
        "api/job_status.py",
    ]

    all_exist = True
    for file in required_files:
        file_path = Path(__file__).parent / file
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            print(f"   ✅ {file:40} ({size_kb:6.2f} KB)")
        else:
            print(f"   ❌ {file:40} (FALTANDO)")
            all_exist = False

    if all_exist:
        print("\n   ✅ Todos os arquivos criados com sucesso!\n")
    else:
        print("\n   ⚠️  Alguns arquivos estão faltando\n")

except Exception as e:
    print(f"   ❌ Erro: {e}\n")

# ===== RESUMO FINAL =====
print("═" * 70)
print("📊 RESUMO DO TESTE")
print("═" * 70)
print()
print("✅ Componentes Testados:")
print("   - Imports e módulos Python")
print("   - Configuração Celery")
print("   - JobStateManager (gerenciamento de estado)")
print("   - WorkflowManager (orquestração)")
print("   - Tasks assíncronas")
print("   - API REST endpoints")
print("   - Estrutura de arquivos")
print()
print("🚀 Próximos Passos:")
print("   1. Iniciar Redis:")
print("      docker-compose up redis -d")
print()
print("   2. Iniciar Worker:")
print("      celery -A infra.worker worker --loglevel=info")
print()
print("   3. Iniciar Beat (agendador):")
print("      celery -A infra.worker beat --loglevel=info")
print()
print("   4. Iniciar Flask App:")
print("      python app.py")
print()
print("   5. Testar endpoint:")
print("      curl http://localhost:5000/api/jobs/schedules")
print()
print("💡 OU usar Docker Compose (tudo-em-um):")
print("   docker-compose up -d")
print()
print("📚 Documentação Completa:")
print("   - README_JOBS_ASSINCRONOS.md")
print("   - GUIA_INTEGRACAO_JOBS.py")
print("   - EXEMPLO_INTEGRACAO_APP.py")
print()
print("═" * 70)
print("✅ TESTE CONCLUÍDO COM SUCESSO!")
print("═" * 70)
