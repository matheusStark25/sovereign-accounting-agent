# Script PowerShell para iniciar o Rogio Pro
# Uso: .\start_rogio.ps1

Write-Host "================================" -ForegroundColor Cyan
Write-Host "🤖 ROGIO PRO - Interface Adaptável" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Verificar se Python está instalado
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python encontrado: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python não encontrado!" -ForegroundColor Red
    Write-Host "Instale Python 3.8+ em https://python.org" -ForegroundColor Yellow
    pause
    exit 1
}

# Verificar se o arquivo .env existe
if (-not (Test-Path ".env")) {
    Write-Host "❌ Arquivo .env não encontrado!" -ForegroundColor Red
    Write-Host ""
    Write-Host "📝 Crie um arquivo .env com:" -ForegroundColor Yellow
    Write-Host "GROQ_API_KEY=sua_chave_aqui"
    Write-Host "PORT=5000"
    Write-Host "FLASK_DEBUG=False"
    pause
    exit 1
}

Write-Host "✅ Arquivo .env encontrado" -ForegroundColor Green

# Verificar se app.py existe
if (-not (Test-Path "app.py")) {
    Write-Host "❌ Arquivo app.py não encontrado!" -ForegroundColor Red
    Write-Host "Certifique-se de estar na pasta contabil_agente" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "✅ Arquivos necessários encontrados" -ForegroundColor Green
Write-Host ""

# Iniciar o servidor
Write-Host "================================" -ForegroundColor Cyan
Write-Host "🚀 Iniciando servidor..." -ForegroundColor Yellow
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 Acesse: http://localhost:5000" -ForegroundColor Cyan
Write-Host "📊 API Health: http://localhost:5000/api/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 Pressione Ctrl+C para parar o servidor" -ForegroundColor Yellow
Write-Host ""

# Executar o servidor Python
try {
    python app.py
} catch {
    Write-Host ""
    Write-Host "❌ Erro ao iniciar servidor!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    pause
    exit 1
}
