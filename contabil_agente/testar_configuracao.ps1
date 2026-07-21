# Teste de Configuração do Rogio Pro
# Este script verifica se tudo está configurado corretamente

Write-Host "🔍 Verificando Configuração do Rogio Pro..." -ForegroundColor Cyan
Write-Host ""

$errors = @()
$warnings = @()

# 1. Verificar Python
Write-Host "[1/6] Verificando Python..." -NoNewline
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        if ($major -ge 3 -and $minor -ge 8) {
            Write-Host " ✅ OK ($pythonVersion)" -ForegroundColor Green
        }
        else {
            Write-Host " ⚠️  Versão antiga ($pythonVersion)" -ForegroundColor Yellow
            $warnings += "Python 3.8+ recomendado"
        }
    }
}
catch {
    Write-Host " ❌ ERRO" -ForegroundColor Red
    $errors += "Python não encontrado no PATH"
}

# 2. Verificar pasta routes
Write-Host "[2/6] Verificando estrutura de pastas..." -NoNewline
if (Test-Path "routes\chat.py") {
    Write-Host " ✅ OK" -ForegroundColor Green
}
else {
    Write-Host " ❌ ERRO" -ForegroundColor Red
    $errors += "Pasta routes/chat.py não encontrada"
}

# 3. Verificar arquivo .env
Write-Host "[3/6] Verificando arquivo .env..." -NoNewline
if (Test-Path ".env") {
    $envContent = Get-Content ".env" -Raw
    if ($envContent -match "GROQ_API_KEY=gsk_\w+") {
        Write-Host " ✅ OK (API Key configurada)" -ForegroundColor Green
    }
    elseif ($envContent -match "GROQ_API_KEY=sua_chave") {
        Write-Host " ⚠️  API Key não configurada" -ForegroundColor Yellow
        $warnings += "Configure sua GROQ_API_KEY no arquivo .env"
    }
    else {
        Write-Host " ⚠️  Verificação necessária" -ForegroundColor Yellow
        $warnings += "Verifique se a GROQ_API_KEY está correta no .env"
    }
}
else {
    Write-Host " ⚠️  Arquivo não existe" -ForegroundColor Yellow
    $warnings += "Execute: Copy-Item .env.example .env"
}

# 4. Verificar app.py
Write-Host "[4/6] Verificando app.py..." -NoNewline
if (Test-Path "app.py") {
    Write-Host " ✅ OK" -ForegroundColor Green
}
else {
    Write-Host " ❌ ERRO" -ForegroundColor Red
    $errors += "app.py não encontrado"
}

# 5. Verificar index_adapted.html
Write-Host "[5/6] Verificando index_adapted.html..." -NoNewline
if (Test-Path "index_adapted.html") {
    Write-Host " ✅ OK" -ForegroundColor Green
}
else {
    Write-Host " ❌ ERRO" -ForegroundColor Red
    $errors += "index_adapted.html não encontrado"
}

# 6. Verificar ambiente virtual
Write-Host "[6/6] Verificando ambiente virtual..." -NoNewline
if (Test-Path "..\venv\Scripts\python.exe") {
    Write-Host " ✅ OK" -ForegroundColor Green
}
else {
    Write-Host " ⚠️  Não encontrado" -ForegroundColor Yellow
    $warnings += "Crie o ambiente virtual: python -m venv ..\venv"
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# Resumo
if ($errors.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "✅ TUDO PRONTO!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Para iniciar o servidor, execute:" -ForegroundColor White
    Write-Host "  .\iniciar_servidor.ps1" -ForegroundColor Cyan
}
else {
    if ($errors.Count -gt 0) {
        Write-Host "❌ ERROS ENCONTRADOS:" -ForegroundColor Red
        foreach ($err in $errors) {
            Write-Host "   • $err" -ForegroundColor Red
        }
        Write-Host ""
    }
    
    if ($warnings.Count -gt 0) {
        Write-Host "⚠️  AVISOS:" -ForegroundColor Yellow
        foreach ($warn in $warnings) {
            Write-Host "   • $warn" -ForegroundColor Yellow
        }
        Write-Host ""
    }
    
    Write-Host "Corrija os problemas acima antes de continuar." -ForegroundColor White
}

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
