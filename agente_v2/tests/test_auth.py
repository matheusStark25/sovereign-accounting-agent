try:
    from fastapi.testclient import TestClient
except Exception:
    # fallback to local shim when FastAPI isn't installed in the environment
    import importlib.util
    import os

    shim_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "tools",
            "fastapi_local_disabled",
            "testclient.py",
        )
    )
    spec = importlib.util.spec_from_file_location("fastapi_shim_testclient", shim_path)
    shim = None
    if spec is not None:
        shim = importlib.util.module_from_spec(spec)
        if getattr(spec, "loader", None) is not None and shim is not None:
            spec.loader.exec_module(shim)
    if shim is None:
        class _Shim:
            class TestClient:
                def __init__(self, *a, **k):
                    pass

        shim = _Shim()
    TestClient = shim.TestClient
from agente_v2.main import app


def test_token_and_me():
    client = TestClient(app)
    r = client.post("/token", data={"username": "alice", "password": "secret"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    token = data["access_token"]
    r2 = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    j = r2.json()
    assert j["username"] == "alice"
