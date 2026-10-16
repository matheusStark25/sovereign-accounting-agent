"""
Configurações centralizadas do sistema
Mantém todas as variáveis de ambiente e paths organizados
"""

import logging
import os
import secrets
from pathlib import Path

from .app_config import AppConfig

logger = logging.getLogger(__name__)


# Load persistent security env file if present (contabil_agente/.env.security)
# This allows setting SECRET_KEY and BASE_DIR for local/dev without requiring
# external tools. Values already present in the environment are NOT overwritten.
try:
    base_dir = Path(__file__).parent.parent
    env_file = base_dir / ".env.security"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                # Do not override explicit environment variables
                os.environ.setdefault(k, v)
except Exception:
    # Fail silently — config falls back to defaults
    logger.debug("No .env.security loaded or failed to parse it")


class Config:
    """Compatibilidade: wrapper sobre `AppConfig`.

    Mantém a API esperada por módulos que importam `Config` enquanto
    centraliza valores em `core/app_config.py`.
    """

    # Segurança
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION = 86400

    # Groq / AI
    GROQ_API_KEY = AppConfig.GROQ_API_KEY
    MODEL_NAME = AppConfig.AI_MODEL
    TEMPERATURE = AppConfig.AI_TEMPERATURE

    # Diretórios (mantém nomes esperados por outros módulos)
    # Prefer explicit BASE_DIR from environment; fallback to AppConfig
    _base = os.getenv("BASE_DIR")
    if _base:
        BASE_DIR = str(Path(_base))
    else:
        BASE_DIR = str(AppConfig.BASE_DIR)

    DOCUMENTS_DIR = str(Path(BASE_DIR) / "documents")
    ASSINATURAS_DIR = str(Path(BASE_DIR) / "assinaturas")
    LOGOS_DIR = str(Path(BASE_DIR) / "logos")
    UPLOADS_DIR = str(AppConfig.UPLOAD_FOLDER)
    LOGS_DIR = str(Path(BASE_DIR) / "logs")
    DB_DIR = str(Path(BASE_DIR) / "db")
    DB_PATH = str(Path(BASE_DIR) / "db" / "contabil_agent.db")

    # Tom de voz padrão
    TOM_VOZ = os.getenv("TOM_VOZ", "informal")

    # Autenticação admin (simples)
    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASS = os.getenv("ADMIN_PASS", "changeme")

    # AWS S3 (opcional)
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
    AWS_REGION = os.getenv("AWS_REGION")

    @classmethod
    def validate(cls):
        """Valida configurações essenciais e cria diretórios necessários."""
        if not cls.GROQ_API_KEY:
            logger.warning(
                "GROQ_API_KEY não definida - chamadas LLM estarão desabilitadas"
            )

        # Em produção (ou quando forçada), exigir um diretório WORM explícito
        env = os.getenv("ENVIRONMENT", os.getenv("FLASK_ENV", "development")).lower()
        strict_worm = os.getenv("FORCE_STRICT_WORM", "0") == "1"

        if env in ("production", "prod") or strict_worm:
            # Requer que EVIDENCIAS_PATH (ou BASE_DIR) seja explicitamente configurado
            evid_path = os.getenv("EVIDENCIAS_PATH") or os.getenv("BASE_DIR")
            if not evid_path:
                raise RuntimeError(
                    "WORM obrigatório em produção: defina EVIDENCIAS_PATH (ou BASE_DIR) com um diretório seguro"
                )

            p = Path(evid_path)
            # Cria se necessário e testa permissões
            try:
                p.mkdir(parents=True, exist_ok=True)
                testfile = p / (".perm_check_%s" % os.urandom(4).hex())
                with open(testfile, "w") as f:
                    f.write("ok")
                testfile.unlink()
            except Exception as e:
                raise RuntimeError(f"Falha ao preparar EVIDENCIAS_PATH '{p}': {e}")

            # Proteger contra configuração apontando para o código-fonte
            pkg_root = Path(__file__).parent.parent.resolve()
            try:
                resolved = p.resolve()
                if pkg_root == resolved or pkg_root in resolved.parents:
                    raise RuntimeError(
                        f"EVIDENCIAS_PATH ({resolved}) não pode estar dentro do código-fonte ({pkg_root})"
                    )
            except RuntimeError:
                raise
            except Exception:
                # Se não for possível resolver, tratar como erro de segurança
                raise RuntimeError(
                    "Falha ao validar EVIDENCIAS_PATH (resolução de caminho falhou)"
                )

        # Delegar criação de pastas para AppConfig, mas também garantir
        # que os diretórios derivados de BASE_DIR existam (quando BASE_DIR
        # é sobrescrito via env/.env.security)
        try:
            AppConfig.create_folders()
        except Exception:
            logger.debug(
                "AppConfig.create_folders() falhou; criando diretórios do Config"
            )

        # Garantir diretórios esperados por Config
        for d in [
            cls.DOCUMENTS_DIR,
            cls.ASSINATURAS_DIR,
            cls.LOGOS_DIR,
            cls.UPLOADS_DIR,
            cls.LOGS_DIR,
            cls.DB_DIR,
        ]:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except Exception:
                logger.exception("Falha ao criar diretório %s", d)


# Validar na importação (comportamento antigo preservado)
try:
    Config.validate()
except Exception:
    logger.exception("Falha ao validar Config na importação")
