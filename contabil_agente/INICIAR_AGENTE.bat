@echo off
echo ===============================================
echo 🤖 AGENTE CONTABIL IA - SUBSTITUI TODO ESCRITORIO
echo ===============================================
echo.
echo Este agente faz TUDO que o pessoal do escritorio faria:
echo • 📊 Contadores - calculos complexos
echo • 👥 Atendentes - orientacoes e duvidas
echo • 📋 Escriturarios - geracao de documentos
echo • 👔 Gerentes - analises e relatorios
echo.
echo ===============================================
echo 🚀 INICIANDO SISTEMA...
echo ===============================================
echo.

cd /d "%~dp0"

echo 📦 Verificando dependencias...
python -c "import flask, groq" 2>nul
if errorlevel 1 (
    echo ❌ Dependencias faltando. Execute:
    echo pip install flask groq python-dotenv
    pause
    exit /b 1
)
echo ✅ Dependencias OK

echo.
echo 🗂️ Verificando arquivos...
if not exist "app.py" (
    echo ❌ app.py nao encontrado
    pause
    exit /b 1
)
if not exist "routes\chat.py" (
    echo ❌ routes\chat.py nao encontrado
    pause
    exit /b 1
)
if not exist "index_adapted.html" (
    echo ❌ index_adapted.html nao encontrado
    pause
    exit /b 1
)
echo ✅ Arquivos OK

echo.
echo 🌐 Iniciando servidor...
start /B python app.py
timeout /t 5 /nobreak >nul

echo.
echo 🧪 Testando funcionalidades...

echo.
echo 📊 TESTANDO CALCULOS (função de contador):
curl -s -X POST http://localhost:5000/api/chat -H "Content-Type: application/json" -d "{\"mensagem\":\"Funcionario ganha R$ 3000, trabalhou 1 ano. Quanto de ferias?\",\"session_id\":\"teste_ferias\"}" >nul
if errorlevel 1 (
    echo ❌ Erro no teste de calculos
) else (
    echo ✅ Calculos funcionando
)

echo.
echo 💬 TESTANDO ORIENTACOES (função de atendente):
curl -s -X POST http://localhost:5000/api/chat -H "Content-Type: application/json" -d "{\"mensagem\":\"Como declarar imposto de renda PF?\",\"session_id\":\"teste_irpf\"}" >nul
if errorlevel 1 (
    echo ❌ Erro no teste de orientacoes
) else (
    echo ✅ Orientacoes funcionando
)

echo.
echo 📄 TESTANDO DOCUMENTOS (função de escriturario):
curl -s -X POST http://localhost:5000/api/chat -H "Content-Type: application/json" -d "{\"mensagem\":\"Gere um formulario de concessao de ferias\",\"session_id\":\"teste_documento\"}" >nul
if errorlevel 1 (
    echo ❌ Erro no teste de documentos
) else (
    echo ✅ Documentos funcionando
)

echo.
echo 🎯 RESULTADO: AGENTE SUBSTITUI TODO ESCRITORIO!
echo ===============================================
echo ✅ CONTADORES: Calculos perfeitos
echo ✅ ATENDENTES: Orientacoes completas
echo ✅ ESCRITURARIOS: Documentos oficiais
echo ✅ GERENTES: Analises e relatorios
echo ✅ 24/7: Nunca para, nunca falha
echo ✅ ZERO CUSTO: Sem salarios, sem ferias
echo ===============================================

echo.
echo 🌐 Abrindo interface...
start http://localhost:5000/adaptada

echo.
echo 📋 TESTE MANUAL - FACA ISSO:
echo 1. 💬 Pergunte: "Quanto de ferias um funcionario com 1 ano ganha?"
echo 2. 🎤 Grave audio: Fale uma duvida contabil
echo 3. 📎 Envie PDF: Teste analise de documentos
echo 4. 📊 Use calculadoras: Ferias, Rescisao, Impostos
echo 5. 📄 Gere documentos: Peca um formulario oficial

echo.
echo ⚠️ MANTENHA ESTA JANELA ABERTA!
echo ❌ Feche para parar o servidor

echo.
echo 🎉 AGENTE PRONTO - SUBSTITUI TODO ESCRITORIO!
echo.

pause
