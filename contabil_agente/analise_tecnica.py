#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Análise técnica completa do sistema"""

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

print("=" * 80)
print("🔍 ANÁLISE TÉCNICA DO FRONTEND")
print("=" * 80)

# Configurar Chrome headless
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")

try:
    print("\n📌 Iniciando Chrome...")
    driver = webdriver.Chrome(options=chrome_options)

    print("📌 Acessando http://localhost:5000/adaptada...")
    driver.get("http://localhost:5000/adaptada")

    # Esperar página carregar
    time.sleep(3)

    print("\n" + "=" * 80)
    print("📊 ANÁLISE DA PÁGINA")
    print("=" * 80)

    # Verificar título
    print(f"\n✓ Título: {driver.title}")

    # Verificar se input existe
    try:
        input_field = driver.find_element(By.ID, "dashboardMessageInput")
        print(f"✓ Campo de input encontrado: {input_field.tag_name}")
        print(f"  - Visível: {input_field.is_displayed()}")
        print(f"  - Habilitado: {input_field.is_enabled()}")
        print(f"  - Placeholder: {input_field.get_attribute('placeholder')}")
        print(f"  - Posição Y: {input_field.location['y']}px")
    except Exception as e:
        print(f"✗ Campo de input NÃO encontrado: {e}")

    # Verificar botão de enviar
    try:
        send_button = driver.find_element(
            By.XPATH, "//button[contains(text(), 'Enviar')]"
        )
        print("✓ Botão enviar encontrado")
        print(f"  - Visível: {send_button.is_displayed()}")
        print(f"  - Habilitado: {send_button.is_enabled()}")
    except Exception as e:
        print(f"✗ Botão de enviar: {e}")

    # Verificar div de mensagens
    try:
        messages_div = driver.find_element(By.ID, "dashboardChatMessages")
        print("✓ Div de mensagens encontrada")
        print(f"  - Visível: {messages_div.is_displayed()}")
        print(f"  - Altura: {messages_div.size['height']}px")
    except Exception as e:
        print(f"✗ Div de mensagens: {e}")

    # Verificar erros JavaScript
    print("\n" + "=" * 80)
    print("🐛 ERROS JAVASCRIPT")
    print("=" * 80)

    logs = driver.get_log("browser")
    if logs:
        for log in logs:
            if log["level"] in ["SEVERE", "ERROR"]:
                print(f"✗ {log['level']}: {log['message']}")
    else:
        print("✓ Nenhum erro JavaScript detectado")

    # TESTE DE ENVIO DE MENSAGEM
    print("\n" + "=" * 80)
    print("🧪 TESTE DE ENVIO DE MENSAGEM")
    print("=" * 80)

    try:
        input_field = driver.find_element(By.ID, "dashboardMessageInput")

        # Rolar até o elemento
        driver.execute_script("arguments[0].scrollIntoView(true);", input_field)
        time.sleep(1)

        # Digite mensagem
        print("\n📝 Digitando mensagem de teste...")
        input_field.clear()
        input_field.send_keys("Olá, teste automático!")

        # Enviar com Enter
        print("📤 Enviando com Enter...")
        input_field.send_keys(Keys.RETURN)

        # Esperar resposta (máximo 15 segundos)
        print("⏳ Aguardando resposta da IA...")

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "message-bot"))
        )

        # Verificar se resposta apareceu
        bot_messages = driver.find_elements(By.CLASS_NAME, "message-bot")
        if bot_messages:
            print("✅ SUCESSO! Resposta recebida!")
            print(f"   Número de mensagens do bot: {len(bot_messages)}")
            last_msg = bot_messages[-1].text[:100]
            print(f"   Última mensagem: {last_msg}...")
        else:
            print("✗ Nenhuma resposta recebida")

    except Exception as e:
        print(f"✗ Erro no teste de envio: {e}")

    # Screenshot para diagnóstico (salva no repositório, não em caminho absoluto)
    print("\n📸 Capturando screenshot...")
    screenshot_path = "contabil_agente/screenshot_debug.png"
    driver.save_screenshot(screenshot_path)
    print(f"   Salvo em: {screenshot_path}")

    print("\n" + "=" * 80)
    print("✅ ANÁLISE CONCLUÍDA")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ ERRO FATAL: {e}")
    import traceback

    traceback.print_exc()

finally:
    if "driver" in locals():
        driver.quit()
        print("\n🔒 Chrome fechado")
