"""
Configuração global de logging estruturado
"""

import logging
import sys
from pathlib import Path
from typing import Any

import structlog


def configurar_logging(
    nivel: str = "INFO", arquivo_log: str | None = None, formato_json: bool = False
) -> None:
    """
    Configura logging estruturado para toda a aplicação

    Args:
        nivel: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        arquivo_log: Caminho do arquivo de log (opcional)
        formato_json: Se True, usa formato JSON, senão formato console
    """

    # Configurar nível
    nivel_logging = getattr(logging, nivel.upper(), logging.INFO)

    # Configurar processadores do structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if formato_json:
        # Formato JSON para produção
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Formato colorido para desenvolvimento
        processors.extend(
            [
                structlog.dev.ConsoleRenderer(colors=True),
            ]
        )

    # Configurar structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(nivel_logging),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configurar logging padrão do Python
    handlers = []

    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(nivel_logging)
    handlers.append(console_handler)

    # Handler para arquivo (se especificado)
    if arquivo_log:
        log_path = Path(arquivo_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(arquivo_log, encoding="utf-8")
        file_handler.setLevel(nivel_logging)
        handlers.append(file_handler)

    # Configuração básica
    logging.basicConfig(
        format="%(message)s",
        level=nivel_logging,
        handlers=handlers,
    )

    # Silenciar logs excessivos de bibliotecas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


def get_logger(nome: str) -> Any:
    """
    Obtém logger estruturado para um módulo

    Args:
        nome: Nome do módulo (normalmente __name__)

    Returns:
        Logger estruturado
    """
    return structlog.get_logger(nome)


# Configuração padrão (development)
configurar_logging(nivel="INFO", formato_json=False)
