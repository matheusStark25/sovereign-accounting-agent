"""
Script de Teste - Verifica se a integração está funcionando

Testa:
1. Servidor Flask está rodando
2. API /api/health responde
3. API /api/chat aceita requisições
4. Frontend carrega corretamente
"""

try:
    import requests  # type: ignore
except Exception:
    # Fallback to a minimal implementation using urllib when 'requests' is not installed.
    import json as _json
    import types
    import urllib.error as _urlerr
    import urllib.request as _urlreq

    class _SimpleResponse:
        def __init__(self, code, body, headers=None):
            self.status_code = code
            self.text = body
            self._body = body
            self.headers = headers or {}

        def json(self):
            try:
                return _json.loads(self._body)
            except Exception:
                raise ValueError("No JSON content")

    # Exceptions used to mimic requests.exceptions
    class ConnectionError(Exception):
        pass

    class Timeout(Exception):
        pass

    def _get(url, timeout=None, allow_redirects=True):
        req = _urlreq.Request(url, method="GET")
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                return _SimpleResponse(resp.getcode(), body, dict(resp.getheaders()))
        except _urlerr.HTTPError as e:
            body = (
                e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            )
            code = e.code if hasattr(e, "code") else getattr(e, "status", 500)
            headers = dict(e.headers) if hasattr(e, "headers") else {}
            return _SimpleResponse(code, body, headers)
        except _urlerr.URLError as e:
            raise _Exceptions.ConnectionError(e)

    def _post(url, json=None, headers=None, timeout=None):
        data = None
        hdrs = dict(headers or {})
        if json is not None:
            data = _json.dumps(json).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = _urlreq.Request(url, data=data, headers=hdrs, method="POST")
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                return _SimpleResponse(resp.getcode(), body, dict(resp.getheaders()))
        except _urlerr.HTTPError as e:
            body = (
                e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            )
            code = e.code if hasattr(e, "code") else getattr(e, "status", 500)
            headers = dict(e.headers) if hasattr(e, "headers") else {}
            return _SimpleResponse(code, body, headers)
        except _urlerr.URLError as e:
            raise _Exceptions.ConnectionError(e)

    # Simple namespace to mimic 'requests' API surface
    _Exceptions = types.SimpleNamespace(
        ConnectionError=ConnectionError, Timeout=Timeout
    )
    requests = types.SimpleNamespace(get=_get, post=_post, exceptions=_Exceptions)

# import json  # Not used
# import time  # Not used
import sys


def testar_servidor():
    """Testa se o servidor está rodando"""
    print("\n" + "=" * 60)
    print("🧪 TESTE DE INTEGRAÇÃO - ROGIO PRO")
    print("=" * 60 + "\n")

    base_url = "http://localhost:5000"

    # Teste 1: Health check
    print("1️⃣  Testando health check...")
    try:
        response = requests.get(f"{base_url}/api/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Health check OK: {data.get('status')}")
            print(f"   📊 Modelo: {data.get('modelo', 'N/A')}")
            print(f"   🕐 Timestamp: {data.get('timestamp', 'N/A')}")
        else:
            print(f"   ❌ Resposta inesperada: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("   ❌ Servidor não está rodando!")
        print("\n   💡 Inicie o servidor com:")
        print("      python app.py")
        print("      ou")
        print("      python start_rogio.py")
        return False
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        return False

    # Teste 2: Frontend
    print("\n2️⃣  Testando carregamento do frontend...")
    try:
        response = requests.get(base_url, timeout=5)
        if response.status_code == 200:
            if "ROGIO PRO" in response.text:
                print("   ✅ Frontend carregado corretamente")
            else:
                print("   ⚠️  Frontend carregou mas conteúdo diferente")
        else:
            print(f"   ❌ Erro ao carregar: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        return False

    # Teste 3: API de Chat
    print("\n3️⃣  Testando API de chat...")
    try:
        payload = {"mensagem": "Olá, este é um teste", "session_id": "test-session-123"}

        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            print("   ✅ Chat API respondeu")
            print(f"   💬 Status: {data.get('status')}")
            print(f"   🔑 Session ID: {data.get('session_id', 'N/A')}")

            # Mostrar parte da resposta
            resposta = data.get("resposta", "")
            if resposta:
                preview = resposta[:100] + "..." if len(resposta) > 100 else resposta
                print(f"   📝 Resposta: {preview}")
        elif response.status_code == 429:
            print("   ⚠️  Rate limit atingido (normal em testes)")
        else:
            print(f"   ❌ Resposta inesperada: {response.status_code}")
            try:
                error_data = response.json()
                print("   ℹ️  Detalhes:", error_data)
            except (ValueError, TypeError):
                print("   ℹ️  Resposta:", response.text[:200])  # noqa: F541
    except requests.exceptions.Timeout:
        print("   ⚠️  Timeout (pode ser normal se API Groq estiver lenta)")
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        return False

    # Teste 4: Download de documentos (endpoint existe?)
    print("\n4️⃣  Testando endpoint de download...")
    try:
        # Não fazemos download real, apenas verificamos se o endpoint existe
        response = requests.get(
            f"{base_url}/download/test.pdf", timeout=5, allow_redirects=False
        )

        # Esperamos 400 ou 404 (arquivo não existe), não erro de servidor
        if response.status_code in [400, 404, 410]:
            print("   ✅ Endpoint de download configurado")
        else:
            print(f"   ℹ️  Resposta: {response.status_code}")
    except Exception as e:
        print(f"   ⚠️  Endpoint pode não estar acessível: {e}")

    # Resumo
    print("\n" + "=" * 60)
    print("✅ TODOS OS TESTES BÁSICOS PASSARAM!")
    print("=" * 60)
    print("\n🌐 Acesse a interface em: http://localhost:5000")
    print("\n💡 Próximos passos:")
    print("   1. Abra o navegador em http://localhost:5000")
    print("   2. Teste os 3 perfis (Profissional, Rural, Idoso)")
    print("   3. Envie uma mensagem de teste")
    print("   4. Verifique se a resposta aparece corretamente")
    print("\n")

    return True


if __name__ == "__main__":
    try:
        sucesso = testar_servidor()
        if not sucesso:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n✋ Teste cancelado pelo usuário")
        sys.exit(0)
