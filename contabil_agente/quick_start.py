"""
Script de inicialização ULTRA-RÁPIDA do servidor Maria Helena
Abre o navegador INSTANTANEAMENTE enquanto o servidor inicializa
"""

import os
import threading
import time
import webbrowser

from app import app

print("\n" + "=" * 60)
print("⚡ MARIA HELENA - STARTUP ULTRA-RÁPIDO")
print("=" * 60 + "\n")


# Abre o navegador IMEDIATAMENTE (mesmo antes do servidor estar pronto)
def open_browser():
    time.sleep(0.5)  # Pequeno delay para dar tempo do servidor começar
    print("🌐 Abrindo navegador...")
    webbrowser.open("http://localhost:5000/adaptada")


# Inicia thread para abrir navegador
browser_thread = threading.Thread(target=open_browser, daemon=True)
browser_thread.start()

# Agora importa e roda o servidor
print("🚀 Iniciando servidor Flask...\n")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    # Flask development server - SEM reloader para velocidade máxima
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,  # Debug desligado para velocidade
        threaded=True,
        use_reloader=False,  # CRÍTICO: sem reloader = startup instantâneo
    )
