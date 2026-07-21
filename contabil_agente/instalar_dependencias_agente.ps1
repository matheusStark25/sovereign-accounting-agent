# Script de instalação de dependências para Agente Contábil Completo

Write-Host "🚀 Instalando dependências do Agente Contábil..." -ForegroundColor Green

# Ativar ambiente virtual
& "..\venv\Scripts\Activate.ps1"

Write-Host "`n📦 Instalando bibliotecas de processamento de documentos..." -ForegroundColor Cyan

# Processa mento de PDFs
# Use pypdf (substituto do PyPDF2)
pip install pypdf

# Processamento de imagens (OCR)
pip install Pillow

# Processamento de planilhas
pip install pandas openpyxl xlrd

# Análise de dados
pip install numpy

Write-Host "`n✅ Dependências instaladas com sucesso!" -ForegroundColor Green
Write-Host "`n📋 OPCIONAL - Para OCR completo de imagens, instale Tesseract:" -ForegroundColor Yellow
Write-Host "   1. Baixe: https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
Write-Host "   2. Execute: pip install pytesseract" -ForegroundColor Yellow
Write-Host "`n🚀 Inicie o servidor: .\venv\Scripts\python.exe contabil_agente\start_rogio.py" -ForegroundColor Green
