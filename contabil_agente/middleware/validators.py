"""
Validadores e sanitizadores de entrada para proteção contra payloads malformados.
"""

import logging
import re
from functools import wraps
from typing import Any, Dict, Optional, Tuple

from flask import jsonify, request

logger = logging.getLogger(__name__)


class InputValidator:
    """Validador de inputs com regras configuráveis."""

    @staticmethod
    def sanitize_string(
        value: str, max_length: int = 10000, allow_html: bool = False
    ) -> str:
        """
        Sanitiza string removendo caracteres perigosos.

        Args:
            value: String a ser sanitizada
            max_length: Comprimento máximo permitido
            allow_html: Se False, remove tags HTML
        """
        if not isinstance(value, str):
            return str(value)

        # Limita tamanho
        value = value[:max_length]

        # Remove caracteres de controle perigosos
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)

        # Remove HTML se não permitido
        if not allow_html:
            value = re.sub(r"<[^>]+>", "", value)

        return value.strip()

    @staticmethod
    def validate_json(
        data: Any, schema: Optional[Dict] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Valida estrutura JSON e tipos de dados.

        Returns:
            (is_valid, error_message)
        """
        if not isinstance(data, dict):
            return False, "Payload deve ser um objeto JSON"

        if schema:
            for field, field_type in schema.items():
                if field in data:
                    if not isinstance(data[field], field_type):
                        return (
                            False,
                            f"Campo '{field}' deve ser do tipo {field_type.__name__}",
                        )

        return True, None

    @staticmethod
    def validate_chat_message(mensagem: str) -> Tuple[bool, Optional[str]]:
        """Valida mensagem de chat."""
        if not mensagem or not isinstance(mensagem, str):
            return False, "Mensagem deve ser uma string não vazia"

        mensagem = mensagem.strip()

        if len(mensagem) == 0:
            return False, "Mensagem não pode ser vazia"

        if len(mensagem) > 10000:
            return False, "Mensagem muito longa (máximo 10000 caracteres)"

        # Verifica se não é apenas caracteres especiais
        if not re.search(r"[a-zA-Z0-9À-ÿ]", mensagem):
            return False, "Mensagem deve conter texto válido"

        return True, None

    @staticmethod
    def validate_session_id(session_id: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Valida formato de session ID."""
        if session_id is None:
            return True, None  # Session ID é opcional

        if not isinstance(session_id, str):
            return False, "Session ID deve ser string"

        # Valida formato UUID
        uuid_pattern = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
        if not re.match(uuid_pattern, session_id.lower()):
            return False, "Session ID deve ser um UUID válido"

        return True, None

    @staticmethod
    def validate_file_upload(
        file_obj: Any, allowed_extensions: list = None, max_size_mb: int = 10
    ) -> Tuple[bool, Optional[str]]:
        """Valida upload de arquivo."""
        if allowed_extensions is None:
            allowed_extensions = ["pd", "jpg", "jpeg", "png", "xlsx", "xls", "csv"]

        if not file_obj or not hasattr(file_obj, "filename"):
            return False, "Arquivo inválido"

        filename = file_obj.filename.lower()

        # Verifica extensão
        if not any(filename.endswith(f".{ext}") for ext in allowed_extensions):
            return (
                False,
                f"Extensão não permitida. Permitidas: {', '.join(allowed_extensions)}",
            )

        # Verifica tamanho (se possível)
        if hasattr(file_obj, "content_length") and file_obj.content_length:
            if file_obj.content_length > max_size_mb * 1024 * 1024:
                return False, f"Arquivo muito grande. Máximo: {max_size_mb}MB"

        # Verifica caracteres perigosos no nome
        if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename):
            return False, "Nome de arquivo contém caracteres inválidos"

        return True, None


def validate_request_json(schema: Optional[Dict] = None, sanitize: bool = True):
    """
    Decorator para validar JSON da requisição.

    Args:
        schema: Dicionário com campos obrigatórios e tipos esperados
        sanitize: Se True, sanitiza strings automaticamente

    Uso:
        @app.route('/api/chat', methods=['POST'])
        @validate_request_json({'mensagem': str})
        def chat():
            data = request.get_json()
            # data já está validado
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Tenta obter JSON de forma segura
            try:
                data = request.get_json(force=True, silent=False)
            except Exception as e:
                logger.warning(f"JSON inválido: {e}")
                return (
                    jsonify(
                        {
                            "erro": "JSON malformado",
                            "detalhes": "Verifique a sintaxe do JSON enviado",
                            "status": "bad_request",
                        }
                    ),
                    400,
                )

            if data is None:
                return (
                    jsonify(
                        {
                            "erro": "Payload vazio",
                            "detalhes": "Envie um JSON válido no corpo da requisição",
                            "status": "bad_request",
                        }
                    ),
                    400,
                )

            # Valida estrutura
            validator = InputValidator()
            is_valid, error = validator.validate_json(data, schema)

            if not is_valid:
                return (
                    jsonify(
                        {
                            "erro": "Validação falhou",
                            "detalhes": error,
                            "status": "validation_error",
                        }
                    ),
                    400,
                )

            # Sanitiza strings se solicitado
            if sanitize and isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str):
                        data[key] = validator.sanitize_string(value)

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def validate_chat_input(f):
    """
    Decorator específico para validar input de chat.

    Valida:
    - Mensagem não vazia e dentro do limite
    - Session ID no formato correto (se fornecido)
    - Sanitiza inputs
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            return (
                jsonify(
                    {
                        "erro": "JSON inválido",
                        "detalhes": "Verifique a sintaxe do JSON enviado",
                        "status": "bad_request",
                    }
                ),
                400,
            )

        if not data:
            return jsonify({"erro": "Payload vazio", "status": "bad_request"}), 400

        validator = InputValidator()

        # Valida mensagem
        mensagem = data.get("mensagem", "").strip()
        is_valid, error = validator.validate_chat_message(mensagem)
        if not is_valid:
            return (
                jsonify(
                    {
                        "erro": "Mensagem inválida",
                        "detalhes": error,
                        "status": "validation_error",
                    }
                ),
                400,
            )

        # Valida session_id
        session_id = data.get("session_id")
        is_valid, error = validator.validate_session_id(session_id)
        if not is_valid:
            return (
                jsonify(
                    {
                        "erro": "Session ID inválido",
                        "detalhes": error,
                        "status": "validation_error",
                    }
                ),
                400,
            )

        # Sanitiza dados
        data["mensagem"] = validator.sanitize_string(mensagem, max_length=10000)

        return f(*args, **kwargs)

    return decorated_function
