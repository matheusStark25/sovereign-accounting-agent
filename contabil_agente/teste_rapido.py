#!/usr/bin/env python3
"""
TESTE RÁPIDO DO AGENTE CONTÁBIL
Script simples para testar todas as funcionalidades
"""

import os
import subprocess
import sys
import time
import webbrowser

import requests


def verificar_dependencias():
    """Verifica se as dependências estão instaladas"""
    try:
        import dotenv  # noqa: F401
        import flask  # noqa: F401
        import groq  # noqa: F401

        print("✅ Dependências básicas OK")
        return True
    except ImportError as e:
        print(f"❌ Dependência faltando: {e}")
        print("Execute: pip install flask groq python-dotenv")
        return False


def verificar_arquivos():
    """Verifica se os arquivos necessários existem"""
    arquivos_necessarios = ["app.py", "routes/chat.py", "index_adapted.html"]

    for arquivo in arquivos_necessarios:
        if os.path.exists(arquivo):
            print(f"✅ {arquivo} encontrado")
        else:
            print(f"❌ {arquivo} não encontrado")
            return False
    return True


def testar_servidor():
    """Testa se o servidor responde"""
    try:
        response = requests.get("http://localhost:5000/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Servidor online: {data.get('status', 'unknown')}")
            return True
        else:
            print(f"❌ Servidor respondeu com status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao conectar com servidor: {e}")
        return False


def testar_api_chat():
    """Testa a API de chat"""
    try:
        payload = {
            "mensagem": "Olá, preciso de ajuda com cálculo de férias",
            "session_id": "teste_rapido",
        }
        response = requests.post(
            "http://localhost:5000/api/chat", json=payload, timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            resposta = data.get("resposta", "")[:100]
            print(f"✅ API Chat funcionando: {resposta}...")
            return True
        else:
            print(f"❌ API Chat erro: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Erro na API Chat: {e}")
        return False


def iniciar_servidor():
    """Inicia o servidor em background"""
    print("🚀 Iniciando servidor...")
    try:
        # Iniciar servidor em background
        process = subprocess.Popen(
            [sys.executable, "app.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
        )

        # Aguardar servidor iniciar
        print("⏳ Aguardando servidor iniciar...")
        time.sleep(3)

        # Verificar se processo ainda está rodando
        if process.poll() is None:
            print("✅ Servidor iniciado com sucesso")
            return process
        else:
            stdout, stderr = process.communicate()
            print("❌ Servidor falhou ao iniciar:")
            print(f"STDOUT: {stdout.decode()}")
            print(f"STDERR: {stderr.decode()}")
            return None

    except Exception as e:
        print(f"❌ Erro ao iniciar servidor: {e}")
        return None


def abrir_navegador():
    """Abre o navegador na interface"""
    url = "http://localhost:5000/adaptada"
    print(f"🌐 Abrindo navegador em: {url}")
    try:
        webbrowser.open(url)
        print("✅ Navegador aberto")
    except Exception as e:
        print(f"❌ Erro ao abrir navegador: {e}")
        print(f"Por favor, acesse manualmente: {url}")


def main():
    print("🧠 TESTE RÁPIDO - AGENTE CONTÁBIL IA")
    print("=" * 50)

    # Verificações iniciais
    print("\n1. Verificando dependências...")
    if not verificar_dependencias():
        return

    print("\n2. Verificando arquivos...")
    if not verificar_arquivos():
        return

    # Verificar se servidor já está rodando
    print("\n3. Verificando servidor...")
    servidor_rodando = testar_servidor()

    servidor_process = None
    if not servidor_rodando:
        print("\n4. Iniciando servidor...")
        servidor_process = iniciar_servidor()
        if not servidor_process:
            return

        # Aguardar mais um pouco
        time.sleep(2)

        # Testar novamente
        if not testar_servidor():
            print("❌ Servidor não conseguiu iniciar")
            return

    print("\n5. Testando API...")
    if testar_api_chat():
        print("✅ API funcionando perfeitamente")
    else:
        print("⚠️ API com problemas, mas interface pode funcionar")

    print("\n6. Abrindo interface...")
    abrir_navegador()

    print("\n" + "=" * 50)
    print("🎉 TESTE CONCLUÍDO!")
    print("\n📋 O QUE TESTAR NA INTERFACE:")
    print("• 💬 Chat com IA - pergunte sobre contabilidade")
    print("• 🎤 Gravação de áudio - fale suas dúvidas")
    print("• 📎 Upload de arquivos - envie PDFs/planilhas")
    print("• 📊 Calculadoras - férias, rescisão, impostos")
    print("• 📄 Geração de documentos - PDFs oficiais")
    print("\n🔄 O agente substitui completamente o pessoal do escritório!")

    if servidor_process:
        print("\n⚠️ Servidor foi iniciado por este script")
        print("❌ Feche este terminal para parar o servidor")

    print("\n✅ PRONTO PARA USAR!")


if __name__ == "__main__":
    main()
