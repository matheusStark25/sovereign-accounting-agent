import requests

payload = {
    "session_id": "test-session-automated",
    # Usar a chave 'mensagem' para compatibilidade com clientes em PT-BR
    "mensagem": "Por favor, gere o documento de rescisão. Nome: João Silva. CPF: 123.456.789-01. Salário R$3000. Aviso prévio indenizado.",
}

try:
    r = requests.post("http://127.0.0.1:5000/api/chat", json=payload, timeout=20)
    print("STATUS", r.status_code)
    print(r.text)
except Exception as e:
    print("ERROR", str(e))
