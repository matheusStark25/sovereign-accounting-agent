import sys
import traceback

from app import app

client = app.test_client()
try:
    resp = client.post("/api/chat", json={"mensagem": "Teste E2E", "session_id": None})
    print("STATUS", resp.status_code)
    print(resp.get_data(as_text=True))
except Exception:
    traceback.print_exc()
    sys.exit(1)
