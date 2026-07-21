"""
Sistema de Logs Estruturados (JSON)
"""

import json
import logging
import sys
from datetime import datetime, timezone

from flask import g, has_request_context


class JSONFormatter(logging.Formatter):
    """Formatter que gera logs em JSON"""

    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Adicionar contexto da request se disponível
        if has_request_context():
            log_obj["empresa_id"] = getattr(g, "empresa_id", None)
            log_obj["trace_id"] = getattr(g, "trace_id", None)

        # Adicionar exception info se houver
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Adicionar campos extras
        if hasattr(record, "empresa_id"):
            log_obj["empresa_id"] = record.empresa_id
        if hasattr(record, "trace_id"):
            log_obj["trace_id"] = record.trace_id
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id

        return json.dumps(log_obj, ensure_ascii=False)


def setup_json_logging(app=None, level=logging.INFO):
    """Configura logging JSON para toda a aplicação"""

    # Criar handler para stdout garantindo encoding UTF-8 para evitar
    # UnicodeEncodeError em consoles com encodings locais (ex.: cp1252).
    import io

    try:
        utf8_stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        handler = logging.StreamHandler(utf8_stdout)
    except Exception:
        # Fallback para ambientes onde buffer não exista (por exemplo, testes
        # que substituem sys.stdout). Usa sys.stdout diretamente como último recurso.
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(JSONFormatter())

    # Não registrar em arquivo por padrão para evitar escrita indesejada em produção

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []  # Remover handlers existentes
    root_logger.addHandler(handler)

    # Configurar loggers específicos
    for logger_name in ["werkzeug", "flask", "gunicorn"]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.handlers = []
        logger.addHandler(handler)
        logger.propagate = False

    if app:
        app.logger.handlers = []
        app.logger.addHandler(handler)
        app.logger.setLevel(level)

    logging.info("JSON logging configurado")


def get_logger(name):
    """Retorna logger configurado"""
    return logging.getLogger(name)
