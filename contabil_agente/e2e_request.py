import requests

url = "http://127.0.0.1:5000/api/chat"
try:
    r = requests.post(
        url, json={"mensagem": "Teste via requests", "session_id": None}, timeout=10
    )
    print(r.status_code)
    print(r.text)
except Exception as e:
    print("ERROR", e)
