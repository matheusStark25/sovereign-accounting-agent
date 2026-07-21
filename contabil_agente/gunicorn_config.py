# ConfiguraÃ§Ã£o Gunicorn para ProduÃ§Ã£o
# Arquivo: gunicorn_config.py

import multiprocessing
import os

# ConfiguraÃ§Ãµes de Bind
bind = "0.0.0.0:5000"
backlog = 2048

# Workers
workers = multiprocessing.cpu_count() * 2 + 1  # FÃ³rmula recomendada
worker_class = "gevent"  # Para WebSocket e async
worker_connections = 1000
max_requests = 1000  # Restart workers apÃ³s N requests (evita memory leak)
max_requests_jitter = 50

# Timeouts
timeout = 120  # 2 minutos (para cÃ¡lculos pesados)
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "agente_dp_contabil"

# Server mechanics
daemon = False
pidfile = "gunicorn.pid"
user = None
group = None
tmp_upload_dir = None

# SSL (se necessÃ¡rio)
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"


# Hooks para inicializaÃ§Ã£o customizada
def on_starting(server):
    """Executado quando Gunicorn inicia"""
    print("ð Iniciando Agente DP - Sistema Profissional")

    # Cria diretÃ³rio de logs se nÃ£o existir
    os.makedirs("logs", exist_ok=True)


def when_ready(server):
    """Executado quando servidor estÃ¡ pronto"""
    print("â Servidor pronto para receber requisiÃ§Ãµes")
    print(f"ð Workers: {workers}")
    print(f"ð Bind: {bind}")


def on_exit(server):
    """Executado quando Gunicorn termina"""
    print("ð Encerrando Agente DP gracefully")


def worker_int(worker):
    """Executado quando worker recebe SIGINT"""
    print(f"â ï¸ Worker {worker.pid} interrompido")


def pre_fork(server, worker):
    """Antes de fork do worker"""


def post_fork(server, worker):
    """Depois de fork do worker"""
    print(f"â¨ Worker {worker.pid} iniciado")


def worker_abort(worker):
    """Quando worker Ã© abortado"""
    print(f"â Worker {worker.pid} abortado (timeout ou erro)")
