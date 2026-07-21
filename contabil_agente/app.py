import sys
import os
import logging
from pathlib import Path
import jwt
import json
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import Flask  # type: ignore[reportMissingImports]
from flask import make_response
from flask import send_from_directory
from flask import jsonify
from flask import request

# Ensure parent directory is in sys.path for absolute imports to work
# This is needed when running from inside contabil_agente/ directory
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    import magic  # type: ignore[reportMissingImports]
except Exception:
    # Fallback lightweight magic-like interface when python-magic is not available.
    # Provides minimal MIME sniffing from a bytes buffer for common file types
    class _FallbackMagic:
        def from_buffer(self, buf, mime=True):
            if not isinstance(buf, (bytes, bytearray)):
                try:
                    buf = bytes(buf)
                except Exception:
                    return "application/octet-stream"

            b = buf[:8]
            # PDF
            if b.startswith(b"%PDF"):
                return "application/pdf"
            # PNG
            if b.startswith(b"\x89PNG"):
                return "image/png"
            # JPEG
            if b.startswith(b"\xff\xd8\xff") or b.startswith(b"\xff\xd8"):
                return "image/jpeg"
            # ZIP / Office Open XML (docx, xlsx, pptx)
            if b.startswith(b"PK\x03\x04"):
                return "application/zip"
            # GIF
            if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
                return "image/gif"
            # Plain text heuristic: many ASCII bytes and newlines
            try:
                text_sample = buf[:256].decode("utf-8")
                if "\n" in text_sample or " " in text_sample:
                    # treat as text if decodable
                    return "text/plain"
            except Exception:
                pass
            return "application/octet-stream"

    magic = _FallbackMagic()

try:
    from contabil_agente.core.app_config import AppConfig
except Exception:
    try:
        from core.app_config import AppConfig
    except Exception:

        class AppConfig:
            # sensible defaults for standalone fallback
            MAX_CONTENT_LENGTH = 16 * 1024 * 1024
            JSON_AS_ASCII = False
            # default upload folder when configuration is not available
            UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")


try:
    from flask_cors import CORS  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover - fallback when flask-cors is not installed
    logging.getLogger(__name__).warning(
        "flask-cors not installed; CORS will not be enabled"
    )

    def CORS(app, **kwargs):
        """Fallback no-op CORS when flask-cors is unavailable."""
        return app


try:
    from dotenv import load_dotenv  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover - fallback when python-dotenv is not installed
    logging.getLogger(__name__).warning(
        "python-dotenv not installed; .env will not be loaded"
    )

    def load_dotenv(*args, **kwargs):
        """Fallback no-op for load_dotenv when python-dotenv is unavailable."""
        return False


try:
    from contabil_agente.api.job_status import register_job_api
except Exception:
    try:
        from api.job_status import register_job_api
    except Exception:

        def register_job_api(app):
            # fallback no-op if job API not available
            return None


# AppConfig import handled above with fallbacks


try:
    from contabil_agente.middleware.security import init_security
except Exception:
    try:
        from middleware.security import init_security
    except Exception:

        def init_security(app):
            return None


# Test hook: force legacy fallback for chat routes when set (useful for tests)
if os.getenv("FORCE_LEGACY_CHAT", "0") == "1":
    chat_multi_tenant_bp = None
else:
    try:
        from contabil_agente.routes.chat_multi_tenant import chat_multi_tenant_bp
    except Exception:
        try:
            from routes.chat_multi_tenant import chat_multi_tenant_bp
        except Exception:
            chat_multi_tenant_bp = None

if os.getenv("FORCE_LEGACY_CHAT", "0") == "1":
    chat_refactored_bp = None
else:
    try:
        from contabil_agente.routes.chat_refactored import chat_refactored_bp
    except Exception:
        try:
            from routes.chat_refactored import chat_refactored_bp
        except Exception:
            chat_refactored_bp = None
# If a refactored chat blueprint was imported, try to mount it at startup so
# `/api/chat` is available. Some deployment setups register blueprints elsewhere;
# mounting here is a safe default for the development server.
# registration is performed after the Flask `app` has been created below
try:
    # Prefer explicit package import when running from project root
    from contabil_agente.utils.health_check import deep_health_check
except Exception:
    try:
        from utils.health_check import deep_health_check
    except Exception:
        # Provide a fallback that returns a degraded health structure
        def deep_health_check():
            return {
                "status": "degraded",
                "checks": [],
                "message": "deep_health_check not available",
            }


try:
    from utils.logger import setup_json_logging
except Exception:
    # minimal fallback logger setup
    def setup_json_logging(app, level=logging.INFO):
        h = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        h.setFormatter(fmt)
        logging.getLogger().addHandler(h)
        logging.getLogger().setLevel(level)


# optional DB health (guarded import)
# Define defaults so names exist regardless of import success
DatabaseService = None
OperationalLegacyWorker = None
Supervisor = None

try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None

try:
    from contabil_agente.services.operational_legacy_worker import (
        OperationalLegacyWorker,
    )
except Exception:
    OperationalLegacyWorker = None

try:
    from contabil_agente.services.workflow_manager import Supervisor
except Exception:
    Supervisor = None

# IngestionService: try to import real implementation, otherwise provide a minimal fallback
try:
    from contabil_agente.services.ingestion_service import IngestionService
except Exception:
    try:
        from services.ingestion_service import IngestionService
    except Exception:

        class IngestionService:
            """Simple fallback ingestion service used when the real
            implementation is not available. Saves uploaded files to the
            configured upload folder and returns a compatible result dict.
            """

            def __init__(
                self, upload_folder, chunk_size=65536, max_content_length=None
            ):
                self.upload_folder = upload_folder
                self.chunk_size = chunk_size
                self.max_content_length = max_content_length
                try:
                    os.makedirs(self.upload_folder, exist_ok=True)
                except Exception:
                    pass

            def _safe_filename(self, name):
                # basic sanitization to avoid directory traversal
                return os.path.basename(name) or "uploaded_file"

            def save(
                self,
                fileobj,
                filename,
                empresa_id=None,
                user_id=None,
                remote_addr="",
                user_agent="",
            ):
                fn = self._safe_filename(
                    filename or getattr(fileobj, "filename", "uploaded_file")
                )
                dest = os.path.join(self.upload_folder, fn)

                # duplicate detection
                if os.path.exists(dest):
                    return {
                        "status": "error",
                        "code": "DUPLICATE_FILE",
                        "message": "file already exists",
                    }

                try:
                    # If it's awerkzeug FileStorage, it has a save method
                    if hasattr(fileobj, "save"):
                        fileobj.save(dest)
                    else:
                        # fallback: write stream in chunks
                        with open(dest, "wb") as w:
                            data = fileobj.read()
                            if data is None:
                                # try iterating
                                for chunk in fileobj:
                                    w.write(chunk)
                            else:
                                w.write(data)

                    return {"status": "success", "filename": fn, "path": dest}
                except Exception as e:
                    return {"status": "error", "code": "IO_ERROR", "message": str(e)}


# Carregar variáveis de ambiente: procurar em `contabil_agente/.env` e na raiz do projeto
env_candidates = [
    Path(__file__).parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]

for _env in env_candidates:
    if not _env.exists():
        continue
    # Tenta usar load_dotenv quando disponível; se ele não carregar (retorna False)
    # ou não estiver presente, tenta um parser manual como fallback.
    try:
        try:
            loaded = load_dotenv(dotenv_path=_env)
        except Exception:
            loaded = False

        if loaded:
            logging.getLogger(__name__).info(f"✔ .env carregado: {_env}")
            break

        # load_dotenv retornou False ou não realizou o carregamento; faz parse manual
        try:
            with open(_env, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        key, value = line.strip().split("=", 1)
                        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
            logging.getLogger(__name__).info(f"✔ .env carregado (manual): {_env}")
            break
        except Exception:
            continue
    except Exception:
        # Segurança: se algo inesperado acontecer, não interrompe o bootstrap
        logging.getLogger(__name__).warning(f"Falha ao tentar carregar .env: {_env}")
        continue

# Carregar variÃ¡veis de seguranÃ§a (se existir)
security_env_path = Path(__file__).parent / ".env.security"
if security_env_path.exists():
    try:
        try:
            sec_loaded = load_dotenv(dotenv_path=security_env_path)
        except Exception:
            sec_loaded = False

        if sec_loaded:
            logger = logging.getLogger(__name__)
            logger.info("✔ Configuração de segurança carregada")
        else:
            # Manual parse quando necessário
            try:
                with open(
                    security_env_path, "r", encoding="utf-8", errors="replace"
                ) as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith("#"):
                            key, value = line.strip().split("=", 1)
                            os.environ[key] = value.strip().strip('"').strip("'")
                logging.getLogger(__name__).info(
                    "✔ Configuração de segurança carregada (manual)"
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Falha ao carregar .env.security manualmente: {e}"
                )
    except Exception as e:
        logging.getLogger(__name__).warning(
            f"Erro inesperado ao tentar carregar .env.security: {e}"
        )
        # JOBS: API de jobs assÃ­ncronos (rotas /api/jobs/*)


# Caminho absoluto base do mÃ³dulo
base_dir = os.path.dirname(os.path.abspath(__file__))

# Criar aplicaÃ§Ã£o Flask
# Mapear explicitamente a pasta de arquivos estÃ¡ticos para garantir
# que `/static/...` resolva corretamente para a pasta `static` dentro do
# pacote `contabil_agente` (usa caminho absoluto para evitar ambiguidade de
# execuÃ§Ã£o via VS Code / start_server.py).

app = Flask(
    __name__,
    static_folder=os.path.join(
        base_dir, "static"
    ),  # Ajuste se estiver dentro de subpasta
    static_url_path="/static",
)

# 🔐 Configurar Flask.session com SECRET_KEY para persistir confirmações entre requisições
app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY", "dev-secret-key-change-in-production"
)
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1 hour

CORS(app)


def extract_jwt(request):
    auth = request.headers.get("Authorization", "").split()
    if len(auth) == 2 and auth[0].lower() == "bearer":
        try:
            return jwt.decode(auth[1], options={"verify_signature": False})
        except Exception:
            return None
    return None


def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosnif"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "default-src 'none';"
    return response


# Global safety: coerce any non-Response (e.g., accidental tuple returns)
@app.after_request
def _coerce_response_obj_global(resp):
    from flask import make_response

    try:
        if isinstance(resp, tuple):
            return make_response(*resp)
    except Exception:
        try:
            logging.getLogger(__name__).exception(
                "Failed while coercing response object"
            )
        except Exception:
            pass
    return resp


# Explicitly set rate limit storage URL to avoid Flask-Limiter warning when
# no storage backend is configured (pytest runs and development).
# Can be overridden by setting the environment variable `RATELIMIT_STORAGE_URL`.
app.config.setdefault(
    "RATELIMIT_STORAGE_URL", os.getenv("RATELIMIT_STORAGE_URL", "memory://")
)

# Initialize Limiter (uses configured `RATELIMIT_STORAGE_URL`).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=app.config.get("RATELIMIT_STORAGE_URL"),
)

# If a refactored chat blueprint was imported earlier, try to register it now
# after `app` exists so `/api/chat` endpoints are mounted.
try:
    # If the module wasn't imported earlier (or import failed), attempt import now
    bp = (
        globals().get("chat_refactored_bp")
        if "chat_refactored_bp" in globals()
        else None
    )
    if not bp:
        try:
            from contabil_agente.routes.chat_refactored import chat_refactored_bp as bp
        except Exception:
            try:
                from routes.chat_refactored import chat_refactored_bp as bp
            except Exception:
                bp = None
                logging.getLogger(__name__).warning(
                    "chat_refactored import failed at startup; blueprint not available",
                    exc_info=True,
                )

    if bp:
        try:
            app.register_blueprint(bp)
            logging.getLogger(__name__).info(
                "Registered chat_refactored blueprint at startup"
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to register chat_refactored blueprint at startup"
            )
except Exception:
    pass

# Fallback seguro: expor diretamente /api/text-to-speech se a função existir
try:
    try:
        from contabil_agente.routes.chat import text_to_speech as _text_to_speech

        try:
            app.add_url_rule(
                "/api/text-to-speech",
                endpoint="text_to_speech_direct",
                view_func=_text_to_speech,
                methods=["POST"],
            )
            logging.getLogger(__name__).info(
                "Registered direct /api/text-to-speech endpoint"
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Could not add /api/text-to-speech rule: {e}"
            )
    except Exception:
        # function not present or import failed
        pass
except Exception:
    pass

# Registrar o blueprint legado `chat_blueprint` (contém TTS e endpoints antigos)
try:
    try:
        from contabil_agente.routes import chat_blueprint

        if chat_blueprint:
            try:
                app.register_blueprint(chat_blueprint)
                logging.getLogger(__name__).info("Registered legacy chat_blueprint")
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Could not register legacy chat_blueprint: {e}"
                )
    except Exception:
        # Falha ao importar o blueprint legado — não é crítico
        pass
except Exception:
    pass


@app.route("/api/v1/upload", methods=["POST"])
@limiter.limit("10/minute")
def upload_controller():
    user = extract_jwt(request)
    if not user:
        return jsonify({"error": "MISSING_OR_INVALID_TOKEN", "code": "AUTH"}), 401
    empresa_id = user.get("empresa_id")
    user_id = user.get("user_id")
    # Empresa_id pode vir na query, body ou form
    req_empresa_id = (
        request.form.get("empresa_id")
        or request.args.get("empresa_id")
        or (
            request.json.get("empresa_id") if request.is_json and request.json else None
        )
    )
    if req_empresa_id and req_empresa_id != empresa_id:
        return jsonify({"error": "EMPRESA_ID_MISMATCH", "code": "AUTH"}), 403
    if "file" not in request.files:
        return jsonify({"error": "NO_FILE", "code": "EMPTY_FILE"}), 400
    file = request.files["file"]
    filename = file.filename or "uploaded_file"
    # MIME type (deep)
    _ = magic.from_buffer(file.read(2048), mime=True)
    file.seek(0)
    ingestion = IngestionService(
        str(AppConfig.UPLOAD_FOLDER),
        chunk_size=65536,
        max_content_length=AppConfig.MAX_CONTENT_LENGTH,
    )
    result = ingestion.save(
        file,
        filename,
        empresa_id,
        user_id,
        request.remote_addr or "",
        request.headers.get("User-Agent", ""),
    )
    status = (
        201
        if result.get("status") == "success"
        else (409 if result.get("code") == "DUPLICATE_FILE" else 400)
    )

    # IntegraÃ§Ã£o das ferramentas apÃ³s upload bem-sucedido
    if status == 201 and result.get("status") == "success":
        try:
            import sys
            import os
            import importlib.util

            current_dir = os.path.dirname(os.path.abspath(__file__))
            agente_path = os.path.join(
                current_dir, "agente_contabilidade", "__init__.py"
            )
            spec = importlib.util.spec_from_file_location(
                "agente_contabilidade", agente_path
            )
            agente_mod = importlib.util.module_from_spec(spec)
            sys.modules["agente_contabilidade"] = agente_mod
            spec.loader.exec_module(agente_mod)
            CalculadoraRescisao = getattr(agente_mod, "CalculadoraRescisao")
            GeradorDocumento = getattr(agente_mod, "GeradorDocumento")

            # Reabrir o arquivo salvo para ler o JSON validado
            saved_path = result.get("path")
            with open(saved_path, "r", encoding="utf-8") as f:
                dados_json = json.load(f)
            # Cálculo
            calc = CalculadoraRescisao(dados_json)
            resultados = calc.calcular()
            # PDF
            sha256 = result.get("file_hash") or result.get("sha256") or ""
            gerador = GeradorDocumento(resultados, sha256=sha256)
            pdf_path = gerador.gerar_pdf()
            # Link relativo para download
            pdf_filename = os.path.basename(pdf_path)
            pdf_url = f"/static/downloads/{pdf_filename}"
            # Log
            logging.getLogger("upload_controller").info(f"PDF gerado: {pdf_url}")
            # Resposta expandida
            result["pdf_url"] = pdf_url
            result["pdf_filename"] = pdf_filename
        except Exception as e:
            logging.getLogger("upload_controller").exception(
                f"Erro ao processar cÃ¡lculo/PDF: {e}"
            )
            result["status"] = "error"
            result["code"] = "PROCESSING_ERROR"
            result["message"] = f"Erro ao processar cÃ¡lculo/PDF: {e}"
            status = 500

    resp = jsonify(result)
    resp = secure_headers(resp)
    return resp, status


# Global operational worker instance (set at bootstrap if available)


operational_worker = None


# ðŸ” Inicializar camada de seguranÃ§a ANTES de registrar blueprints
try:
    init_security(app)
except Exception as e:
    # Se falhar, continua sem seguranÃ§a (modo compatibilidade)
    logging.getLogger(__name__).info(
        f"âš ï¸  Camada de seguranÃ§a nÃ£o iniciada (fallback): {e}. Sistema rodando sem proteÃ§Ã£o RBAC/Auditoria."
    )


# Fallback global para decodificaÃ§Ã£o de JSON com encodings nÃ£o-UTF8 (ex.: PowerShell)
@app.before_request
def _decode_json_fallback():
    """Tenta decodificar o body JSON manualmente antes que Werkzeug tente,
    aplicando fallback para latin-1/CP1252 quando necessÃ¡rio. Define
    `request._cached_json` para que `request.get_json()` funcione normalmente.
    """
    import json

    if request.mimetype != "application/json":
        return

    try:
        # Se jÃ¡ foi parseado, nÃ£o faz nada
        if getattr(request, "_cached_json", None) is not None:
            return

    except Exception:
        pass
    raw = request.get_data(cache=True)
    if not raw:
        return

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception:
            text = raw.decode("utf-8", errors="replace")

    try:
        parsed = json.loads(text)
        # Armazenar no cache interno do request para uso posterior
        try:
            request._cached_json = parsed
        except Exception:
            # Se por algum motivo nÃ£o for possÃ­vel setar, apenas ignore
            pass
    except Exception:
        # NÃ£o interrompe a requisiÃ§Ã£o; o handler de rota farÃ¡ validaÃ§Ã£o
        try:
            pass  # Imports already at top
        except KeyboardInterrupt:
            print(
                "\nInterrupted during startup (KeyboardInterrupt). Exiting gracefully."
            )
            sys.exit(1)
        except Exception:  # pragma: no cover - diagnÃ³stico amigÃ¡vel
            print("\nERROR: falha ao importar Flask/Jinja2:\n")
            traceback.print_exc()
            if "debugpy" in sys.modules or any("pydevd" in m for m in sys.modules):
                print(
                    "\nPOSSÃVEL CAUSA: o depurador (debugpy/pydevd) pode interferir na inicializaÃ§Ã£o.\n"
                    "Tente executar diretamente no terminal sem o depurador:\n  python contabil_agente\\app.py\n"
                    "ou desative temporariamente a extensÃ£o de depuraÃ§Ã£o.\n"
                )
            else:
                raise
    # exception handling for dynamic chat registration handled above
    # JOBS: API de jobs assÃ­ncronos (rotas /api/jobs/*)
    try:
        if register_job_api is not None:
            register_job_api(app)
        logging.getLogger(__name__).info("Jobs API loaded (inside function fallback)")
    except Exception:
        pass


# JOBS: API de jobs assincronos (rotas /api/jobs/*) - REGISTRO NO NIVEL DO MODULO
try:
    if register_job_api is not None:
        register_job_api(app)
        logging.getLogger(__name__).info("API de Jobs registrada em /api/jobs")
except Exception as e:
    logging.getLogger(__name__).warning(f"API de Jobs nao registrada: {e}")


# SECURE API: Rotas protegidas com camada de seguranÃ§a (rotas /api/v3/secure/*)
try:
    from routes.secure_api import secure_api_bp

    app.register_blueprint(secure_api_bp)
    logger.info("âœ… Secure API Blueprint registrado")
except Exception as e:
    logger.info(f"âš ï¸  Secure API Blueprint nÃ£o registrado (opcional): {e}")
# LEGACY: nÃ£o registramos o blueprint legado para evitar conflito/depreciaÃ§Ã£o


# DESABILITA CACHE COMPLETAMENTE - FORÃ‡A ATUALIZAÃ‡ÃƒO IMEDIATA
@app.after_request
def add_no_cache_headers(response):
    """Headers ULTRA AGRESSIVOS para DESTRUIR qualquer cache"""
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"
    response.headers["Last-Modified"] = "Mon, 01 Jan 1990 00:00:00 GMT"

    # Remove ETag completamente para evitar validaÃ§Ã£o condicional
    response.headers.pop("ETag", None)

    # Headers adicionais para matar cache
    response.headers["X-Accel-Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    # Security: Content Security Policy (relaxed for inline CSS/JS required by frontend)
    # Allow 'unsafe-inline' for both scripts and styles so embedded <style> and inline event handlers work.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'"
    )

    # Ensure basic security headers exist even if full security middleware failed
    # Tests expect these headers to be present; add sensible defaults here as a fallback.
    response.headers.setdefault("X-Content-Type-Options", "nosnif")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")

    return response


# Rotas para servir as interfaces
@app.route("/adaptada")
def index_adaptada():
    """Serve a interface - FORÃ‡A RELOAD com timestamp no conteÃºdo"""
    import time
    from datetime import datetime

    # Caminho absoluto para o arquivo HTML
    html_path = os.path.join(os.path.dirname(__file__), "index_adapted.html")

    # LÃª o arquivo
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Adiciona timestamp ÃšNICO no inÃ­cio do HTML como comentÃ¡rio
    # Isso FORÃ‡A o navegador a ver que o conteÃºdo mudou
    timestamp = int(time.time() * 1000)
    timestamp_comment = (
        f"<!-- CACHE-BUST: {timestamp} | {datetime.now().isoformat()} -->\n"
    )

    # Injeta apÃ³s <!doctype html> ou no inÃ­cio
    if "<!doctype" in content.lower():
        content = content.replace(
            "<!doctype html>", f"<!doctype html>\n{timestamp_comment}", 1
        )
    elif "<!DOCTYPE" in content:
        content = content.replace(
            "<!DOCTYPE html>", f"<!DOCTYPE html>\n{timestamp_comment}", 1
        )
    else:
        content = timestamp_comment + content

    # Cria resposta com conteÃºdo modificado
    response = make_response(content)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    # ðŸ”¥ HEADERS ANTI-CACHE AGRESSIVOS (forÃ§a navegador a SEMPRE recarregar)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    response.headers["X-Accel-Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["ETag"] = f'W/"{timestamp}"'  # ETag Ãºnico por request

    return response


@app.route("/teste")
def pagina_teste():
    """Serve pÃ¡gina de teste simples do chat"""
    return send_from_directory(".", "test_chat.html")


@app.route("/profissional")
def index_profissional():
    """Serve a interface profissional"""
    return send_from_directory(".", "index_profissional.html")


@app.route("/rural")
def index_rural():
    """Serve a interface rural"""
    return send_from_directory(".", "index_rural.html")


@app.route("/idoso")
def index_idoso():
    """Serve a interface para idosos"""
    return send_from_directory(".", "index_idoso.html")


@app.route("/")
def index_root():
    """Serve a interface principal"""
    return send_from_directory(".", "index.html")


@app.route("/simples")
def index_simples():
    """Serve a interface simples (estilo WhatsApp) - ideal para todos os pÃºblicos"""
    return send_from_directory(".", "index_simple.html")


@app.route("/test")
def test_chat():
    """Serve a pÃ¡gina de teste de chat"""
    return send_from_directory(".", "test_chat.html")


# Rota para arquivos estÃ¡ticos
@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve arquivos estÃ¡ticos"""
    # Serve static files from the package's `static` folder so that
    # `/static/...` resolves correctly when the app is started from
    # the workspace root (VS Code launch, start_server.py, etc.).
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return send_from_directory(static_dir, filename)


@app.route("/download/latest")
def download_latest():
    """Serve o PDF mais recente gerado em `contabil_agente/temp_docs`"""
    try:
        from flask import jsonify

        # Preferir pasta `static/downloads` dentro do pacote para expor via HTTP
        downloads_dir = os.path.join(base_dir, "static", "downloads")

        # Se `downloads` nÃ£o existir, fallback para `temp_docs` (compatibilidade)
        if os.path.exists(downloads_dir):
            files_dir = downloads_dir
        else:
            files_dir = os.path.join(os.path.dirname(__file__), "temp_docs")

        if not os.path.exists(files_dir):
            return jsonify({"erro": "Nenhum PDF disponÃ­vel"}), 404

        files = [f for f in os.listdir(files_dir) if f.lower().endswith(".pdf")]
        if not files:
            return jsonify({"erro": "Nenhum PDF disponÃ­vel"}), 404

        files.sort(
            key=lambda fn: os.path.getmtime(os.path.join(files_dir, fn)), reverse=True
        )
        latest = files[0]

        return send_from_directory(files_dir, latest, as_attachment=True)

    except Exception as e:
        logger.error(f"Erro ao servir latest PDF: {e}", exc_info=True)
        try:
            from flask import jsonify, make_response

            return make_response(
                jsonify(
                    {
                        "erro": "Falha ao obter arquivo",
                        "detalhes": str(e),
                        "status": "error",
                    }
                ),
                200,
            )
        except Exception:
            from flask import make_response, jsonify

            return make_response(
                jsonify({"erro": "Falha ao obter arquivo", "status": "error"}), 200
            )


# Backwards-compatible download endpoint when blueprint is not registered
@app.route("/download/<path:filename>")
def download_fallback(filename):
    """Serve arquivos PDF gerados em `contabil_agente/temp_docs` ou `static/downloads`.

    Este handler garante que `/download/<filename>` funcione mesmo que o
    blueprint refatorado nÃ£o tenha sido registrado (Ãºtil durante testes).
    """
    try:
        # Prefer static downloads folder if present
        downloads_dir = os.path.join(base_dir, "static", "downloads")
        candidate = os.path.join(downloads_dir, filename)
        if os.path.exists(candidate):
            return send_from_directory(downloads_dir, filename, as_attachment=True)

        # Fallback para temp_docs dentro do pacote
        temp_dir = os.path.join(os.path.dirname(__file__), "temp_docs")
        candidate2 = os.path.join(temp_dir, filename)
        if os.path.exists(candidate2):
            return send_from_directory(temp_dir, filename, as_attachment=True)

        from flask import jsonify

        return jsonify({"erro": "Arquivo nÃ£o encontrado"}), 404
    except Exception as e:
        logger.exception("Erro no download fallback: %s", e)
        from flask import make_response, jsonify

        return make_response(
            jsonify(
                {
                    "erro": "Erro ao baixar arquivo",
                    "detalhes": str(e),
                    "status": "error",
                }
            ),
            200,
        )


# Health check bÃ¡sico
@app.route("/health")
def health():
    """VerificaÃ§Ã£o de saÃºde bÃ¡sica do servidor"""
    # Retornar um payload simples e vÃ¡lido para probes e testes.
    try:
        return jsonify({"status": "ok"}), 200
    except Exception:
        # Em caso de falha inesperada, retornar status degraded
        return {"status": "degraded"}, 503


# Health check avanÃ§ado
@app.route("/health/deep")
def health_deep():
    """VerificaÃ§Ã£o de saÃºde completa com dependÃªncias"""
    result = deep_health_check()
    status_code = 200 if result["status"] == "healthy" else 503
    return result, status_code


# Backwards-compatible API health endpoint
@app.route("/api/health")
def api_health():
    """Compatibility endpoint used by older startup scripts and probes."""
    # Minimal JSON payload expected by probes and frontend.
    return jsonify({"status": "ok"})


# Endpoint de debug para visualizar histÃ³rico de sessÃ£o
@app.route("/api/debug/session/<session_id>", methods=["GET"])
def debug_session(session_id):
    """Endpoint de debug para visualizar histÃ³rico de sessÃ£o"""
    try:
        from routes.chat import historico_conversas
    except ImportError:
        try:
            from contabil_agente.routes.chat import historico_conversas
        except ImportError:
            return jsonify({"erro": "histÃ³rico nÃ£o disponÃ­vel"}), 500

    if session_id not in historico_conversas:
        return (
            jsonify(
                {
                    "erro": "sessÃ£o nÃ£o encontrada",
                    "sessoes_disponiveis": list(historico_conversas.keys())[:10],
                }
            ),
            404,
        )

    sessao = historico_conversas[session_id]
    messages_preview = []
    for msg in sessao.get("messages", []):
        content = msg.get("content", "")
        preview = content[:150] + "..." if len(content) > 150 else content
        messages_preview.append({"role": msg.get("role"), "content_preview": preview})

    return jsonify(
        {
            "session_id": session_id,
            "total_messages": len(sessao.get("messages", [])),
            "messages": messages_preview,
            "contexto": sessao.get("contexto"),
            "pending_generation": sessao.get("pending_generation") is not None,
        }
    )


# Exempt health/readiness endpoints from global rate limiting so probes don't get 429 HTML
try:
    limiter.exempt(api_health)
except Exception:
    pass

# Ensure there is a direct `/api/chat` POST handler available for the frontend.
# If a refactored blueprint provides the implementation, delegate to it.
if chat_refactored_bp is None:

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        try:
            try:
                app.logger.info("=== api_chat() iniciado ===")
            except Exception:
                pass

            # Delegate to dynamically-registered handler if present
            try:
                mods = app.config.get("CHAT_REF_MODS")
                if mods and mods.get("module"):
                    mod = mods.get("module")
                    handler = getattr(mod, "chat_minimal", None)
                    if handler:
                        return handler()
            except Exception:
                pass

            # Try legacy handlers
            try:
                from contabil_agente.routes.chat import processar_chat as legacy_chat

                app.logger.info(
                    "=== Chamando legacy_chat (contabil_agente.routes.chat) ==="
                )
                return legacy_chat()
            except Exception:
                try:
                    from routes.chat import processar_chat as legacy_chat

                    app.logger.info("=== Chamando legacy_chat (routes.chat) ===")
                    return legacy_chat()
                except Exception:
                    pass

            # Degraded fallback: parse request and return a minimal Portuguese reply
            import json
            import uuid

            dados = None
            try:
                dados = request.get_json(silent=True)
            except Exception:
                dados = None

            if dados is None:
                raw = request.get_data()
                if raw:
                    try:
                        txt = raw.decode("utf-8")
                    except Exception:
                        try:
                            txt = raw.decode("latin-1")
                        except Exception:
                            txt = raw.decode("utf-8", errors="replace")
                    try:
                        dados = json.loads(txt)
                    except Exception:
                        dados = {"mensagem": txt}
            # 'mensagem' variable removed as it was assigned but never used
            session_id = (
                dados.get("session_id") if isinstance(dados, dict) else None
            ) or str(uuid.uuid4())

            resposta = (
                "(Modo degradado) Serviço principal indisponível no momento; esta é uma resposta temporária. "
                "Por favor, tente novamente em alguns instantes."
            )

            return (
                jsonify(
                    {
                        "resposta": resposta,
                        "message_count": 1,
                        "success": True,
                        "session_id": session_id,
                    }
                ),
                200,
            )

        except Exception:
            try:
                app.logger.exception("Unhandled error in api_chat")
            except Exception:
                pass
            from flask import make_response, jsonify

            fallback_msg = (
                "Houve um pequeno problema técnico. Vou tentar novamente, ok?"
            )
            return make_response(
                jsonify(
                    {
                        "resposta": fallback_msg,
                        "resposta_ia": fallback_msg,
                        "session_id": None,
                        "success": False,
                        "status": "error",
                    }
                ),
                200,
            )

    # Prometheus metrics endpoint


@app.route("/metrics")
def metrics():
    try:
        from contabil_agente.services.monitoring_service import get_monitoring_service

        mon = get_monitoring_service()
        txt = mon.metrics_text()
        from flask import Response

        return Response(txt, mimetype="text/plain; version=0.0.4")
    except Exception:
        from flask import Response

        return Response(
            "# metrics unavailable\n", mimetype="text/plain; version=0.0.4", status=200
        )


@app.route("/ready")
def ready():
    """Readiness probe: DB accessible and minimal dependencies available."""
    try:
        db_ok = False
        try:
            from contabil_agente.services.database_service import DatabaseService

            db = DatabaseService()
            dh = db.health_check()
            db_ok = dh.get("ok", False) and dh.get("integrity_ok", False)
        except Exception:
            db_ok = False

        if db_ok:
            return {"ready": True}
        return {"ready": False}, 503
    except Exception:
        return {"ready": False}, 503


# Provide JSON response for rate limit errors to avoid HTML payloads breaking JSON parsers
@app.errorhandler(429)
def ratelimit_handler(e):
    try:
        return (
            jsonify({"error": "TOO_MANY_REQUESTS", "message": "Rate limit exceeded"}),
            429,
        )
    except Exception:
        from flask import Response

        return Response(
            '{"error":"TOO_MANY_REQUESTS"}', status=429, mimetype="application/json"
        )


# TEST HELPERS (dev-only) - permitir reset de rate limiter durante testes E2E
@app.route("/__test__/reset_ratelimit", methods=["POST", "GET"])
def _reset_ratelimit():
    try:
        # Try several import strategies to locate the middleware's get_rate_limiter
        get_rate_limiter = None
        try:
            from contabil_agente.middleware.rate_limiter import get_rate_limiter  # type: ignore
        except Exception:
            try:
                # fallback to top-level import if package context differs
                from middleware.rate_limiter import get_rate_limiter  # type: ignore
            except Exception:
                # As a last resort, scan loaded modules for a rate_limiter provider
                for mname, mod in list(sys.modules.items()):
                    try:
                        if mod is None:
                            continue
                        if hasattr(mod, "get_rate_limiter") and "rate_limiter" in mname:
                            get_rate_limiter = getattr(mod, "get_rate_limiter")
                            break
                    except Exception:
                        continue

        if get_rate_limiter is None:
            # final attempt: import by name using importlib (handles some loader setups)
            try:
                import importlib

                mod = importlib.import_module("contabil_agente.middleware.rate_limiter")
                get_rate_limiter = getattr(mod, "get_rate_limiter", None)
            except Exception:
                get_rate_limiter = None

        if get_rate_limiter is None:
            raise ImportError("rate_limiter middleware not available")

        rl = get_rate_limiter()
        # In tests we want a reliable reset of the in-memory counters.
        # Clear all rate limiter keys (safer across different identifier formats)
        deleted = []
        try:
            # primary API
            deleted = rl.reset_all(None)
        except Exception:
            # aggressive fallback: clear internal memory store if present
            try:
                if hasattr(rl, "_memory_store"):
                    lock = getattr(rl, "_lock", None)
                    if lock:
                        try:
                            lock.acquire()
                            rl._memory_store.clear()
                            deleted = []
                        finally:
                            try:
                                lock.release()
                            except Exception:
                                pass
                    else:
                        rl._memory_store.clear()
                        deleted = []
            except Exception:
                # best-effort individual clears
                try:
                    rl.reset("127.0.0.1", "per_ip")
                except Exception:
                    pass
                try:
                    rl.reset("::1", "per_ip")
                except Exception:
                    pass
                try:
                    rl.reset("unknown", "per_ip")
                except Exception:
                    pass

        # Also clear legacy in-module rate limit store used by routes/chat.py
        legacy_cleared = 0
        legacy_sample = []
        try:
            # Prefer package-qualified import when running as package
            try:
                from contabil_agente.routes import chat as legacy_chat
            except Exception:
                try:
                    from routes import chat as legacy_chat
                except Exception:
                    legacy_chat = None

            if legacy_chat is not None:
                try:
                    if hasattr(legacy_chat, "rate_limit_ip_store"):
                        legacy_sample = list(legacy_chat.rate_limit_ip_store.keys())[
                            :20
                        ]
                        legacy_cleared = len(legacy_chat.rate_limit_ip_store)
                        legacy_chat.rate_limit_ip_store.clear()
                except Exception:
                    # best-effort: ignore failures clearing legacy store
                    pass
        except Exception:
            # ignore if legacy module not available
            pass

        return {
            "reset": True,
            "cleared_total": len(deleted) if deleted is not None else 0,
            "deleted_keys_sample": deleted[:20] if deleted else [],
            "legacy_cleared_count": legacy_cleared,
            "legacy_cleared_sample": legacy_sample,
        }
    except Exception as e:
        logger.info(f"Falha ao resetar rate limiter (teste): {e}")
        return {"reset": False, "error": str(e)}, 500


# Dev helper: register chat_refactored blueprint into a running server process
@app.route("/__admin__/register_chat_refactored", methods=["POST"])
def _admin_register_chat_refactored():
    try:
        import importlib

        mod = importlib.import_module("contabil_agente.routes.chat_refactored")
        bp = getattr(mod, "chat_refactored_bp", None)
        if bp is None:
            return {
                "registered": False,
                "error": "chat_refactored_bp not found in module",
            }, 404
        # Avoid calling app.register_blueprint at runtime (Flask prohibits after first request).
        # Instead store the module and blueprint for delegation and advise restart for full mounting.
        try:
            app.config.setdefault("CHAT_REF_MODS", {})
            app.config["CHAT_REF_MODS"]["module"] = mod
            app.config["CHAT_REF_MODS"]["bp"] = bp
        except Exception as e:
            return {"registered": False, "error": f"failed to store module: {e}"}, 500
        return {
            "registered": True,
            "note": "module stored for delegation; restart recommended to mount blueprint",
        }
    except Exception as e:
        logger.exception("Failed to register chat_refactored blueprint dynamically")
        return {"registered": False, "error": str(e)}, 500


if __name__ == "__main__":
    # Feedback IMEDIATO para o usuÃ¡rio
    print("\n" + "=" * 60)
    print("SERVIDOR MARIA HELENA - INICIANDO...")
    print("=" * 60 + "\n")

    port = int(os.getenv("PORT", 5000))
    debug = True  # Sempre debug para startup rÃ¡pido

    print(f"Iniciando na porta {port}")
    print(f"Acesse: http://localhost:{port}/adaptada")

    # Verificar se GROQ_API_KEY estÃ¡ configurada
    if not os.getenv("GROQ_API_KEY"):
        print("AVISO: GROQ_API_KEY nÃ£o encontrada! Configure no arquivo .env")

    print("\nSERVIDOR PRONTO! Abrindo navegador...\n")

    # Abrir navegador automaticamente apÃ³s 1.5 segundos
    import webbrowser
    import threading

    def open_browser():
        webbrowser.open(f"http://localhost:{port}/adaptada")

    threading.Timer(1.5, open_browser).start()

    # Start Operational Legacy Worker in background (if available)
    try:
        op_cls = globals().get("OperationalLegacyWorker")
        sup_cls = globals().get("Supervisor")
        if op_cls:
            db = DatabaseService() if DatabaseService else None
            worker = op_cls(db=db)
            # expose globally so HTTP endpoints can trigger resume
            operational_worker = worker
            # start with single worker thread to avoid resource contention at startup
            worker.start(worker_count=int(os.getenv("STARK_OP_WORKERS", "1")))
            print("OperationalLegacyWorker iniciado")

            # register restart callback on Supervisor if available
            try:
                if sup_cls and db:
                    sup = sup_cls(db)

                    # register a real callback that asks the worker to resume from persisted checkpoints
                    try:
                        if hasattr(worker, "resume_from_checkpoint"):
                            sup.register_restart_callback(
                                "operational_legacy", worker.resume_from_checkpoint
                            )
                        else:
                            sup.register_restart_callback(
                                "operational_legacy",
                                lambda wid: db.notify_alert(
                                    f"Supervisor restart requested for {wid}"
                                ),
                            )
                    except Exception:
                        # fallback registration if callback setup fails
                        sup.register_restart_callback(
                            "operational_legacy",
                            lambda wid: db.notify_alert(
                                f"Supervisor restart requested for {wid}"
                            ),
                        )
                    sup.start()
            except Exception:
                print("AVISO: Falha ao iniciar OperationalLegacyWorker (opcional)")

        # Finalmente, iniciar o servidor Flask
        try:
            # ForÃ§ar bind apenas ao loopback e porta 5000 conforme solicitado
            app.run(
                host="127.0.0.1",
                port=5000,
                debug=debug,
                threaded=True,
                use_reloader=False,
            )
        except Exception as e:
            import traceback

            print("AVISO: Falha ao iniciar servidor:", e)
            traceback.print_exc()
            raise
    except Exception:
        # Fallback to ensure startup errors don't leave an unclosed try
        logger.exception("Operational legacy worker bootstrap failed")

    @app.route("/__admin__/resume_operational", methods=["POST", "GET"])
    def _admin_resume_operational():
        """Admin endpoint to trigger resume_from_checkpoint on the operational worker."""
        try:
            expected = os.getenv("ADMIN_OP_RESUME_TOKEN")
            from flask import request, jsonify

            if not expected:
                return (
                    jsonify({"resumed": False, "reason": "admin_token_not_configured"}),
                    403,
                )

            # Accept Authorization: Bearer <token> or ?token=<token>
            token = None
            auth = request.headers.get("Authorization") or request.headers.get(
                "authorization"
            )
            if auth and auth.lower().startswith("bearer "):
                token = auth.split(None, 1)[1]
            if not token:
                token = request.args.get("token")

            if token != expected:
                return jsonify({"resumed": False, "reason": "invalid_token"}), 403

            if operational_worker is None:
                return (
                    jsonify({"resumed": False, "reason": "no_operational_worker"}),
                    404,
                )

            try:
                if hasattr(operational_worker, "resume_from_checkpoint"):
                    operational_worker.resume_from_checkpoint()
                    return jsonify({"resumed": True}), 200
                else:
                    return (
                        jsonify(
                            {"resumed": False, "reason": "worker_has_no_resume_method"}
                        ),
                        400,
                    )
            except Exception as e:
                logger.exception("Error resuming operational worker")
                return jsonify({"resumed": False, "reason": str(e)}), 500
        except Exception as e:
            logger.exception("admin resume failed")
            return {"resumed": False, "error": str(e)}, 500
