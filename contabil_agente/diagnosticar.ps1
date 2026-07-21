# Script de Diagnóstico Automático - Rogio Pro
# Este script identifica e ajuda a resolver problemas comuns

Write-Host "🔍 DIAGNÓSTICO AUTOMÁTICO - ROGIO PRO" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$problemas = @()
$solucoes = @()

# Teste 1: Verificar pasta correta
Write-Host "[1/10] Verificando diretório..." -NoNewline
if (Test-Path "app.py") {
    Write-Host " ✅" -ForegroundColor Green
}
else {
    Write-Host " ❌" -ForegroundColor Red
    $problemas += "Você não está na pasta correta"
    $solucoes += "Execute: cd 'c:\Users\User\Desktop\agent projeto V2\contabil_agente'"
}

# Teste 2: Verificar Python
Write-Host "[2/10] Verificando Python..." -NoNewline
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python") {
        Write-Host " ✅ ($pythonVersion)" -ForegroundColor Green
    }
    else {
        Write-Host " ⚠️" -ForegroundColor Yellow
        $problemas += "Python não encontrado ou versão incompatível"
        $solucoes += "Instale Python 3.8+ de https://python.org"
    }
}
catch {
    Write-Host " ❌" -ForegroundColor Red
    $problemas += "Python não instalado"
    $solucoes += "Baixe e instale Python de https://python.org"
}

# Teste 3: Verificar arquivo .env
Write-Host "[3/10] Verificando .env..." -NoNewline
if (Test-Path ".env") {
    $envContent = Get-Content ".env" -Raw
    if ($envContent -match "GROQ_API_KEY=gsk_\w{40,}") {
        Write-Host " ✅ (API Key configurada)" -ForegroundColor Green
    }
    elseif ($envContent -match "GROQ_API_KEY=your_groq") {
        Write-Host " ❌" -ForegroundColor Red
        $problemas += "API Key não configurada no .env"
        $solucoes += "1. Obtenha chave em: https://console.groq.com/keys`n   2. Edite .env: notepad .env`n   3. Cole a chave: GROQ_API_KEY=gsk_sua_chave"
    }
    else {
        Write-Host " ⚠️" -ForegroundColor Yellow
        $problemas += "API Key pode estar incorreta"
        $solucoes += "Verifique se a chave começa com 'gsk_' e tem ~52 caracteres"
    }
}
else {
    Write-Host " ❌" -ForegroundColor Red
    $problemas += "Arquivo .env não existe"
    $solucoes += "Execute: Copy-Item .env.example .env`n   Depois edite com: notepad .env"
}

# Teste 4: Verificar routes/chat.py
Write-Host "[4/10] Verificando backend..." -NoNewline
if (Test-Path "routes\chat.py") {
    Write-Host " ✅" -ForegroundColor Green
}
else {
    Write-Host " ❌" -ForegroundColor Red
    $problemas += "Arquivo routes/chat.py não encontrado"
    $solucoes += "Verifique se baixou todos os arquivos do projeto"
}

# Teste 5: Verificar index_adapted.html
Write-Host "[5/10] Verificando frontend..." -NoNewline
if (Test-Path "index_adapted.html") {
    Write-Host " ✅" -ForegroundColor Green
}
else {
    Write-Host " ❌" -ForegroundColor Red
    $problemas += "Arquivo index_adapted.html não encontrado"
    $solucoes += "Certifique-se de ter o arquivo HTML na pasta"
}

# Teste 6: Verificar porta 5000
Write-Host "[6/10] Verificando porta 5000..." -NoNewline
$portInUse = netstat -ano | Select-String ":5000" | Select-String "LISTENING"
if ($portInUse) {
    Write-Host " ⚠️ (Porta em uso)" -ForegroundColor Yellow
    $problemas += "Porta 5000 já está sendo usada"
    $solucoes += "Opção 1: Encerre o processo que está usando a porta`nOpção 2: Mude a porta no .env: PORT=5001"
}
else {
    Write-Host " ✅ (Porta livre)" -ForegroundColor Green
}

# Teste 7: Verificar ambiente virtual
Write-Host "[7/10] Verificando ambiente virtual..." -NoNewline
if (Test-Path "..\venv\Scripts\python.exe") {
    Write-Host " ✅" -ForegroundColor Green
}
else {
    Write-Host " ⚠️" -ForegroundColor Yellow
    $problemas += "Ambiente virtual não encontrado"
    $solucoes += "Crie com: python -m venv ..\venv"
}

# Teste 8: Verificar dependências
Write-Host "[8/10] Verificando dependências..." -NoNewline
try {
    $flaskInstalled = pip show flask 2>&1
    $groqInstalled = pip show groq 2>&1
    if ($flaskInstalled -match "Version" -and $groqInstalled -match "Version") {
        Write-Host " ✅" -ForegroundColor Green
    }
    else {
        Write-Host " ⚠️" -ForegroundColor Yellow
        $problemas += "Dependências não instaladas"
        $solucoes += "Execute: pip install -r requirements.txt"
    }
}
catch {
    Write-Host " ⚠️" -ForegroundColor Yellow
    $problemas += "Não foi possível verificar dependências"
    $solucoes += "Execute: pip install -r requirements.txt"
}

# Teste 9: Testar servidor (se estiver rodando)
Write-Host "[9/10] Testando servidor..." -NoNewline
try {
    $response = Invoke-WebRequest -Uri "http://localhost:5000/api/health" -TimeoutSec 2 -ErrorAction Stop
    $data = $response.Content | ConvertFrom-Json
    if ($data.status -eq "online") {
        Write-Host " ✅ (Servidor online)" -ForegroundColor Green
    }
}
catch {
    Write-Host " ⚠️ (Servidor offline)" -ForegroundColor Yellow
    # Não é erro crítico, pode não estar iniciado ainda
}

# Teste 10: Verificar conectividade internet
Write-Host "[10/10] Verificando internet..." -NoNewline
try {
    $ping = Test-Connection -ComputerName "console.groq.com" -Count 1 -Quiet
    if ($ping) {
        Write-Host " ✅" -ForegroundColor Green
    }
    else {
        Write-Host " ⚠️" -ForegroundColor Yellow
        $problemas += "Sem conexão com servidor GROQ"
        $solucoes += "Verifique sua conexão com a internet"
    }
}
catch {
    Write-Host " ⚠️" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan

# Relatório final
if ($problemas.Count -eq 0) {
    Write-Host ""
    Write-Host "🎉 TUDO OK! Sistema pronto para uso!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Próximos passos:" -ForegroundColor White
    Write-Host "  1. Execute: .\iniciar_servidor.ps1" -ForegroundColor Cyan
    Write-Host "  2. Abra: http://localhost:5000/adaptada" -ForegroundColor Cyan
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host "❌ PROBLEMAS ENCONTRADOS ($($problemas.Count))" -ForegroundColor Red
    Write-Host ""
    
    for ($i = 0; $i -lt $problemas.Count; $i++) {
        Write-Host "Problema $($i + 1):" -ForegroundColor Yellow
        Write-Host "  $($problemas[$i])" -ForegroundColor White
        Write-Host ""
        Write-Host "Solução:" -ForegroundColor Green
        Write-Host "  $($solucoes[$i])" -ForegroundColor White
        Write-Host ""
        Write-Host "───────────────────────────────────────────────" -ForegroundColor DarkGray
        Write-Host ""
    }
    
    Write-Host "Após corrigir os problemas, execute este script novamente." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Perguntar se quer ver os logs
$verLogs = Read-Host "Deseja ver informações adicionais de debug? (s/n)"
if ($verLogs -eq "s" -or $verLogs -eq "S") {
    Write-Host ""
    Write-Host "📊 INFORMAÇÕES DE DEBUG" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
    
    # Mostrar conteúdo parcial do .env (sem expor a chave)
    if (Test-Path ".env") {
        Write-Host ""
        Write-Host "Conteúdo do .env (chave mascarada):" -ForegroundColor Yellow
        $envContent = Get-Content ".env"
        foreach ($line in $envContent) {
            if ($line -match "GROQ_API_KEY=(.{4})(.+)") {
                Write-Host "  GROQ_API_KEY=$($matches[1])***[MASCARADO]***" -ForegroundColor White
            }
            elseif ($line -and -not $line.StartsWith("#")) {
                Write-Host "  $line" -ForegroundColor White
            }
        }
    }
    
    # Versão do Python
    Write-Host ""
    Write-Host "Versão do Python:" -ForegroundColor Yellow
    python --version
    
    # Pacotes instalados (principais)
    Write-Host ""
    Write-Host "Pacotes principais instalados:" -ForegroundColor Yellow
    $packages = @("flask", "groq", "reportlab", "flask-cors")
    foreach ($pkg in $packages) {
        $info = pip show $pkg 2>&1 | Select-String "Version"
        if ($info) {
            Write-Host "  $pkg - $info" -ForegroundColor White
        }
        else {
            Write-Host "  $pkg - NÃO INSTALADO" -ForegroundColor Red
        }
    }
    
    # Processos na porta 5000
    Write-Host ""
    Write-Host "Processos na porta 5000:" -ForegroundColor Yellow
    $port5000 = netstat -ano | Select-String ":5000"
    if ($port5000) {
        $port5000 | ForEach-Object { Write-Host "  $_" -ForegroundColor White }
    }
    else {
        Write-Host "  Nenhum processo" -ForegroundColor White
    }
}

Write-Host ""
Read-Host "Pressione Enter para sair"
