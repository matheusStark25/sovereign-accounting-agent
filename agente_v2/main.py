from datetime import timedelta
from datetime import datetime

# Minimal in-memory fallback metrics for environments without prometheus_client
_METRICS = {"ingest_count": 0, "ingest_fallbacks": 0}

try:
    from fastapi import Depends  # type: ignore[reportMissingImports]
    from fastapi import FastAPI  # type: ignore[reportMissingImports]
    from fastapi import HTTPException  # type: ignore[reportMissingImports]
    from fastapi import Security  # type: ignore[reportMissingImports]
    from fastapi.security import OAuth2PasswordRequestForm  # type: ignore[reportMissingImports]
    from fastapi.security import HTTPAuthorizationCredentials  # type: ignore[reportMissingImports]
    from fastapi.security import HTTPBearer  # type: ignore[reportMissingImports]
    from fastapi import UploadFile  # type: ignore[reportMissingImports]
    from fastapi import File  # type: ignore[reportMissingImports]
except Exception:
    # Minimal fallback shims for environments without FastAPI installed (tests/dev)
    from typing import Any
    import importlib.util
    import os

    tc_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "tools",
            "fastapi_local_disabled",
            "testclient.py",
        )
    )
    spec_tc = importlib.util.spec_from_file_location("fastapi_shim_testclient", tc_path)
    shim_tc = None
    if spec_tc is not None:
        shim_tc = importlib.util.module_from_spec(spec_tc)
        if getattr(spec_tc, "loader", None) is not None and shim_tc is not None:
            spec_tc.loader.exec_module(shim_tc)
    # Provide a minimal fallback shim object for TestClient when module couldn't be loaded
    if shim_tc is None:
        class _ShimTC:
            class TestClient:
                def __init__(self, *a, **k):
                    pass

        shim_tc = _ShimTC()

    # Minimal inline shim for FastAPI objects used by our tests
    class FastAPI:
        def __init__(self, *args, **kwargs):
            self._routes = {}
            self._startup_handlers = []

        def route(self, path=None, *args, **kwargs):
            def _decor(f):
                if path:
                    self._routes[path] = f
                return f

            return _decor

        def include_router(self, *args, **kwargs):
            return None

        def get(self, path=None, *args, **kwargs):
            return self.route(path, *args, **kwargs)

        def post(self, path=None, *args, **kwargs):
            return self.route(path, *args, **kwargs)

        def websocket(self, path=None, *args, **kwargs):
            return self.route(path, *args, **kwargs)

        def on_event(self, name: str):
            def _decor(f):
                # register startup/shutdown handlers; call immediately for shim
                if name == "startup":
                    try:
                        f()
                    except Exception:
                        pass
                return f

            return _decor

    class WebSocket:
        def __init__(self, scope: Any = None):
            self.scope = scope

        async def accept(self):
            return None

        async def receive_text(self):
            return ""

        async def send_text(self, data: str):
            return None

    TestClient = shim_tc.TestClient

    def Depends(x: Any = None):
        return x

    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str | None = None):
            super().__init__(detail or "")

    class Security:
        def __init__(self, sec):
            self.sec = sec

    class OAuth2PasswordRequestForm:  # type: ignore
        def __init__(self, username: str = "", password: str = ""):
            self.username = username
            self.password = password

    class HTTPAuthorizationCredentials:  # type: ignore
        def __init__(self, credentials: str):
            self.credentials = credentials

    class HTTPBearer:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class UploadFile:  # type: ignore
        def __init__(self, filename: str, file):
            self.filename = filename
            self._file = file

        async def read(self):
            return self._file.read()

    def File(*args, **kwargs):
        return None


try:
    from pydantic import BaseModel  # type: ignore[reportMissingImports]
except Exception:
    # Minimal BaseModel fallback for environments without pydantic during tests
    class BaseModel:
        def __init__(self, **data):
            for k, v in data.items():
                setattr(self, k, v)

        def dict(self):
            return self.__dict__


from .auth import create_access_token  # noqa: E402
from .auth import decode_access_token  # noqa: E402
from .auth import verify_password  # noqa: E402
from .auth import get_password_hash  # noqa: E402
from .config import settings  # noqa: E402
from .logging_setup import setup_logging  # noqa: E402
from .vault_client import VaultClient  # noqa: E402
from .tasks import enqueue_document_job  # noqa: E402

logger = setup_logging()

app = FastAPI(title=settings.PROJECT_NAME)
security = HTTPBearer()

# Prometheus metrics (module-level). Optional: only active if prometheus_client is installed.
try:
    from prometheus_client import Counter  # type: ignore[reportMissingImports]
    from prometheus_client import generate_latest, CollectorRegistry  # type: ignore[reportMissingImports]

    METRIC_INGEST = Counter("agente_ingest_total", "Total ingests")
    METRIC_INGEST_FALLBACKS = Counter(
        "agente_ingest_fallbacks_total", "Ingests using fallback"
    )
except Exception:
    METRIC_INGEST = None
    METRIC_INGEST_FALLBACKS = None


# --- minimal user store (replace with real user DB / IAM) ---
class User(BaseModel):
    user_id: str
    username: str
    hashed_password: str


_USERS = {
    "alice": User(
        user_id="user-1", username="alice", hashed_password=get_password_hash("secret")
    )
}


def get_vault() -> VaultClient:
    return VaultClient(url=settings.VAULT_URL, token=settings.VAULT_TOKEN)


@app.post("/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = _USERS.get(form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.user_id, expires_delta=access_token_expires
    )
    return {"access_token": token, "token_type": "bearer"}


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> User:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    sub = payload.get("sub")
    # Resolve user from subject
    for u in _USERS.values():
        if u.user_id == sub:
            # attach audit_id to request context (simple example)
            audit_id = f"audit::{u.user_id}::{payload.get('iat') or datetime.utcnow().isoformat()}"
            logger.info(
                "user_authenticated", extra={"user_id": u.user_id, "audit_id": audit_id}
            )
            return u
    raise HTTPException(status_code=401, detail="User not found")


@app.get("/users/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.user_id, "username": current_user.username}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup_event():
    v = get_vault()
    # example: load a certificate secret into memory (do not log private keys)
    cert_pem = v.get_secret("secret/certs", "a1_cert")
    if cert_pem:
        logger.info("vault: cert loaded (present)")
    else:
        logger.info("vault: cert not found or vault not configured")


@app.post("/ingest")
async def ingest_file(
    file: UploadFile = File(...),
    webhook: str | None = None,
    current_user: User = Depends(get_current_user),
):
    data = await file.read()
    # generate audit id for this operation
    audit_id = f"audit::{current_user.user_id}::{datetime.utcnow().isoformat()}"

    # enqueue job asynchronously including user context
    try:
        if METRIC_INGEST is not None:
            try:
                METRIC_INGEST.inc()
            except Exception:
                pass
        job_id = await enqueue_document_job(
            data,
            file.filename,
            webhook,
            user_id=current_user.user_id,
            audit_id=audit_id,
        )
    except Exception:
        # fallback: run inline (sync fallback for dev)
        from .tasks import process_document

        res = await process_document(
            None,
            data,
            file.filename,
            webhook,
            user_id=current_user.user_id,
            audit_id=audit_id,
        )
        if METRIC_INGEST_FALLBACKS is not None:
            try:
                METRIC_INGEST_FALLBACKS.inc()
            except Exception:
                pass
        return {"job": None, "result": res}
    return {"job": job_id, "audit_id": audit_id}


@app.get("/metrics")
def metrics():
    try:
        # simple registry and metrics example (process-global, for demo)
        registry = CollectorRegistry()
        c_ingest = Counter("agente_ingest_total", "Total ingests", registry=registry)
        c_fallback = Counter(
            "agente_ingest_fallbacks_total", "Ingests using fallback", registry=registry
        )
        # mark created metrics as referenced so linters don't flag them as unused
        assert c_ingest is not None and c_fallback is not None
        # For now expose legacy JSON as fallback if prometheus_client not fully instrumented.
        return generate_latest(registry)
    except Exception:
        return {
            "ingest_count": _METRICS["ingest_count"],
            "ingest_fallbacks": _METRICS["ingest_fallbacks"],
        }
