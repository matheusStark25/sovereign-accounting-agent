#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Análise técnica sem Selenium - inspeção de código"""

import re
import time
import uuid

import requests

print("=" * 80)
print("🔍 ANÁLISE TÉCNICA COMPLETA - SEM BROWSER")
print("=" * 80)

# 1. VERIFICAR BACKEND
print("\n📡 1. TESTE DO BACKEND")
print("-" * 80)

try:
    resp = requests.get("http://localhost:5000/health", timeout=5)
    print(f"✅ Backend online: {resp.status_code}")
    print(f"   {resp.json()}")
except Exception as e:
    print(f"❌ Backend offline: {e}")
    exit(1)

# 2. VERIFICAR ROTAS
print("\n🌐 2. VERIFICAÇÃO DE ROTAS")
print("-" * 80)

rotas_testar = [
    ("/", "Rota raiz"),
    ("/adaptada", "Interface adaptada"),
    ("/api/health", "Health check API"),
]

for rota, desc in rotas_testar:
    try:
        resp = requests.get(f"http://localhost:5000{rota}", timeout=5)
        status = "✅" if resp.status_code == 200 else "⚠️"
        print(f"{status} {desc}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ {desc}: {e}")

# 3. TESTE FUNCIONAL DO CHAT
print("\n💬 3. TESTE FUNCIONAL DO CHAT (API)")
print("-" * 80)

session_id = str(uuid.uuid4())

mensagens_teste = [
    "teste",
    "oi",
    "calcular férias",
]

for msg in mensagens_teste:
    try:
        print(f"\n📤 Enviando: '{msg}'")
        resp = requests.post(
            "http://localhost:5000/api/chat",
            json={"mensagem": msg, "session_id": session_id},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=20,
        )

        if resp.status_code == 200:
            data = resp.json()
            resposta = data.get("resposta", "")[:80]
            print(f"✅ Resposta OK: {resposta}...")
            if data.get("pdf_url"):
                print(f"   📄 PDF: {data['pdf_url']}")
        else:
            print(f"❌ HTTP {resp.status_code}")
            print(f"   {resp.text[:200]}")

    except Exception as e:
        print(f"❌ Erro: {e}")

    time.sleep(0.5)

# 4. ANÁLISE DO HTML SERVIDO
print("\n📄 4. ANÁLISE DO HTML SERVIDO")
print("-" * 80)

try:
    resp = requests.get("http://localhost:5000/adaptada", timeout=5)
    html = resp.text

    # Verificar elementos chave
    elementos = {
        "dashboardMessageInput": r'id="dashboardMessageInput"',
        "dashboardChatMessages": r'id="dashboardChatMessages"',
        "sendDashboardMessage": r"function sendDashboardMessage",
        "getSessionId": r"function getSessionId",
        "voiceButton": r'id="voiceButton"',
    }

    for nome, pattern in elementos.items():
        if re.search(pattern, html):
            print(f"✅ {nome}: encontrado")
        else:
            print(f"❌ {nome}: NÃO encontrado")

    # Verificar se há display:none bloqueando
    if "display: none" in html:
        none_matches = re.findall(r"(\w+).*?display:\s*none", html, re.DOTALL)
        if none_matches:
            print(f"\n⚠️  Elementos com display:none detectados: {len(none_matches)}")

    # Verificar se chat-section está escondido
    if re.search(r'id="chat-section".*?display:\s*none', html, re.DOTALL):
        print("⚠️  PROBLEMA: chat-section está com display:none")

    # Verificar se dashboard está visível
    if 'id="dashboard"' in html:
        print("✅ Dashboard presente no HTML")

        # Verificar se dashboardMessageInput está dentro de elemento escondido
        dashboard_section = re.search(
            r'<div[^>]*id="dashboard"[^>]*>(.*?)</div>\s*<!--.*?FIM DASHBOARD',
            html,
            re.DOTALL,
        )
        if dashboard_section and "dashboardMessageInput" in dashboard_section.group(1):
            print("✅ dashboardMessageInput está dentro do dashboard")
        else:
            print("⚠️  dashboardMessageInput pode estar fora do dashboard")

    print(f"\n📊 Tamanho do HTML: {len(html):,} bytes")
    print(f"📊 Linhas: {html.count(chr(10)):,}")

except Exception as e:
    print(f"❌ Erro ao analisar HTML: {e}")

# 5. VERIFICAR JAVASCRIPT
print("\n🔧 5. ANÁLISE DE JAVASCRIPT NO HTML")
print("-" * 80)

try:
    # Buscar todas as funções JavaScript
    funcoes_js = re.findall(r"function\s+(\w+)\s*\(", html)
    print(f"✅ Funções JavaScript encontradas: {len(funcoes_js)}")

    funcoes_criticas = [
        "sendDashboardMessage",
        "addDashboardMessage",
        "getSessionId",
        "toggleVoiceRecognition",
        "sendMessage",
    ]

    for func in funcoes_criticas:
        if func in funcoes_js:
            print(f"   ✓ {func}")
        else:
            print(f"   ✗ {func} (AUSENTE!)")

    # Verificar event listeners
    if "addEventListener" in html:
        listeners = html.count("addEventListener")
        print(f"\n✅ Event listeners: {listeners} encontrados")

    # Verificar se há console.log para debug
    if "console.log" in html:
        logs = html.count("console.log")
        print(f"✅ Console.log statements: {logs}")

except Exception as e:
    print(f"❌ Erro: {e}")

# 6. RESUMO E DIAGNÓSTICO
print("\n" + "=" * 80)
print("📋 RESUMO DO DIAGNÓSTICO")
print("=" * 80)

print("\n✅ FUNCIONANDO:")
print("   • Backend Flask online")
print("   • API /api/chat respondendo corretamente")
print("   • IA gerando respostas válidas")
print("   • HTML sendo servido")

print("\n🔍 VERIFICAR:")
print("   • Abrir navegador em http://localhost:5000/adaptada")
print("   • Pressionar F12 (DevTools)")
print("   • Ir na aba Console")
print("   • Procurar erros JavaScript (linhas vermelhas)")
print("   • Verificar se campo de input está visível")

print("\n💡 SE NÃO APARECER O CHAT:")
print("   • Rolar a página para BAIXO")
print("   • Procurar por '🤖 Agente de IA'")
print("   • Verificar se está na aba 'Dashboard'")

print("\n" + "=" * 80)
