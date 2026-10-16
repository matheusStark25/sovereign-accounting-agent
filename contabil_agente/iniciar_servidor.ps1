# Script para iniciar o servidor Rogio Pro no Windows

Write-Host "🚀 Iniciando Rogio Pro Chat Interface..." -ForegroundColor Green
Write-Host ""

# Verificar se está no diretório correto
if (-not (Test-Path "app.py")) {
    Write-Host "❌ Erro: Execute este script dentro da pasta contabil_agente" -ForegroundColor Red
    exit 1
}

# Verificar se o ambiente virtual existe
$venvPath = "..\venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvPath)) {
    Write-Host "❌ Erro: Ambiente virtual não encontrado em ..\venv" -ForegroundColor Red
    Write-Host "Execute primeiro: python -m venv ..\venv" -ForegroundColor Yellow
    exit 1
}

# Ativar ambiente virtual
Write-Host "📦 Ativando ambiente virtual..." -ForegroundColor Cyan
& $venvPath

# Verificar se .env existe
if (-not (Test-Path ".env")) {
    Write-Host "⚠️  Arquivo .env não encontrado!" -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Write-Host "Copiando .env.example para .env..." -ForegroundColor Cyan
        Copy-Item ".env.example" ".env"
        Write-Host ""
        Write-Host "⚠️  IMPORTANTE: Edite o arquivo .env e adicione sua GROQ_API_KEY" -ForegroundColor Yellow
        Write-Host "Obtenha sua chave em: https://console.groq.com/keys" -ForegroundColor Cyan
        Write-Host ""
        Read-Host "Pressione Enter após configurar o .env para continuar"
    }
}

# Verificar se GROQ_API_KEY está configurada
$envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
if ($envContent -match "GROQ_API_KEY=your_groq_api_key_here" -or -not ($envContent -match "GROQ_API_KEY=\w+")) {
    Write-Host "❌ GROQ_API_KEY não configurada no arquivo .env" -ForegroundColor Red
    Write-Host "Edite o arquivo .env e adicione sua chave da API" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Configuração OK" -ForegroundColor Green
Write-Host ""

# Instalar dependências se necessário
Write-Host "📚 Verificando dependências..." -ForegroundColor Cyan
pip install -q -r requirements.txt

Write-Host ""
Write-Host "🌐 Iniciando servidor..." -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "Acesse a interface em:" -ForegroundColor White
Write-Host "  → Interface Adaptável: http://localhost:5000/adaptada" -ForegroundColor Cyan
Write-Host "  → Interface Profissional: http://localhost:5000/profissional" -ForegroundColor Cyan
Write-Host "  → Interface Rural: http://localhost:5000/rural" -ForegroundColor Cyan
Write-Host "  → Interface Idoso: http://localhost:5000/idoso" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pressione Ctrl+C para encerrar o servidor" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

# Iniciar o servidor
python app.py
