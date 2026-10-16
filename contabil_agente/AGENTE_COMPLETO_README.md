# 🤖 ROGIO PRO - AGENTE CONTÁBIL COMPLETO

> Sistema de IA que faz TUDO que um contador faz - automatizado!

## 🎯 FUNCIONALIDADES DE AGENTE COMPLETO

### 1. 🎤 **GRAVAÇÃO DE ÁUDIO**

- **Como usar**: Clique no ícone 🎤
- **O que faz**: Grava sua voz e transcreve automaticamente
- **Exemplo**: "Preciso calcular rescisão de João, salário 3 mil"
- **Tecnologia**: Whisper API (Groq) - precisão profissional

### 2. 📎 **UPLOAD DE DOCUMENTOS**

- **Como usar**: Clique no ícone 📎
- **Aceita**:
  - ✅ PDFs (notas fiscais, holerites, contratos)
  - ✅ Imagens JPG/PNG (documentos escaneados)
  - ✅ Excel/CSV (planilhas de folha, vendas)
- **O que faz**: Analisa AUTOMATICAMENTE e extrai informações

### 3. 🧠 **ANÁLISE INTELIGENTE**

#### Notas Fiscais

- Extrai valores, impostos, fornecedores
- Calcula créditos de ICMS/IPI
- Gera relatórios de compras/vendas

#### Holerites/Folha de Pagamento

- Valida cálculos de salário
- Verifica descontos (INSS, IRRF)
- Identifica inconsistências

#### Extratos Bancários

- Reconcilia movimentações
- Identifica despesas dedutíveis
- Categoriza lançamentos

#### Planilhas Excel

- Analisa dados financeiros
- Gera gráficos e relatórios
- Identifica padrões e anomalias

### 4. 📄 **GERAÇÃO AUTOMÁTICA DE DOCUMENTOS**

O sistema **detecta automaticamente** quando gerar PDF:

- ✅ Cálculos trabalhistas (férias, rescisão, 13º)
- ✅ Análises fiscais
- ✅ Pareceres técnicos
- ✅ Relatórios de auditoria

### 5. 💡 **SUGESTÕES CONTEXTUAIS**

Após cada resposta, o agente sugere:

- Próximos cálculos relacionados
- Documentos complementares
- Verificações necessárias

## 🚀 INÍCIO RÁPIDO

### 1. Instalar Dependências

```powershell
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"
.\instalar_dependencias_agente.ps1
```

### 2. Iniciar Servidor

```powershell
cd "c:\Users\User\Desktop\agent projeto V2"
.\venv\Scripts\python.exe "contabil_agente\start_rogio.py"
```

### 3. Acessar

Abra: **<http://localhost:5000/adaptada>**

## 💼 EXEMPLOS DE USO REAL

### Exemplo 1: Cálculo de Rescisão

1. Clique em 🎤
2. Fale: "Funcionário João Silva, 2 anos de trabalho, salário R$ 3.500, demissão sem justa causa"
3. Sistema calcula automaticamente:
   - Aviso prévio
   - Férias proporcionais + 1/3
   - 13º proporcional
   - Multa FGTS 40%
4. Gera PDF oficial

### Exemplo 2: Análise de Nota Fiscal

1. Clique em 📎
2. Selecione PDF da nota fiscal
3. Sistema extrai:
   - Valor total
   - Impostos (ICMS, IPI, PIS, COFINS)
   - Fornecedor
   - Produtos
4. Sugere próximas ações (contabilização, créditos)

### Exemplo 3: Validação de Folha

1. Clique em 📎
2. Envie planilha Excel da folha
3. Sistema verifica:
   - Cálculos de salário
   - Descontos corretos (INSS, IRRF)
   - Encargos patronais (INSS 20%, FGTS 8%)
4. Gera relatório com inconsistências

### Exemplo 4: Consultoria Fiscal

1. Digite: "Minha empresa fatura R$ 200k/mês. Simples ou Presumido?"
2. Sistema analisa:
   - Enquadramento tributário
   - Simulação de impostos
   - Economia potencial
3. Gera comparativo em PDF

## 🎨 PERFIS ADAPTATIVOS

O agente detecta AUTOMATICAMENTE seu perfil:

### 👔 Profissional

- Linguagem técnica
- Termos contábeis
- Análises detalhadas
- **Detectado quando**: Usa termos como "EBITDA", "DRE", "compliance"

### 🌾 Rural/Agricultor

- Linguagem simples
- Exemplos práticos
- Foco em ITR, FUNRURAL
- **Detectado quando**: Menciona "fazenda", "plantação", "colheita"

### 👴 Idoso/Aposentado

- Fonte GRANDE
- Alto contraste
- Explicações didáticas
- **Detectado quando**: Fala de "aposentadoria", "pensão", "INSS"

## 🔒 SEGURANÇA

- ✅ Rate limiting (20 req/min, 200/dia)
- ✅ Sanitização de arquivos
- ✅ Validação de uploads
- ✅ PDFs expiram em 24h
- ✅ Limpeza automática de temporários

## 📊 ENDPOINTS DA API

| Endpoint | Método | Função |
| ---------- | -------- | -------- |
| `/api/chat` | POST | Chat com IA |
| `/api/transcribe` | POST | Transcreve áudio |
| `/api/analyze-documents` | POST | Analisa documentos |
| `/api/health` | GET | Status do servidor |
| `/download/<file>` | GET | Download de PDFs |

## 🛠️ TECNOLOGIAS

- **Backend**: Flask 2.3.3
- **IA**: Groq (Llama 3.3 70B + Whisper)
- **PDFs**: ReportLab 4.0.4
- **Documentos**: PyPDF2, Pandas, Pillow
- **Frontend**: HTML5 + Vanilla JavaScript

## 📦 DEPENDÊNCIAS COMPLETAS

```txt
flask>=2.3.3
flask-cors>=4.0.0
python-dotenv>=1.0.0
groq>=0.4.0
reportlab>=4.0.4
PyPDF2>=3.0.0
Pillow>=10.0.0
pandas>=2.0.0
openpyxl>=3.1.0
xlrd>=2.0.0
numpy>=1.24.0
```

## 🎯 PRÓXIMAS EVOLUÇÕES

- [ ] OCR completo com Tesseract
- [ ] Integração com e-CAC (Receita Federal)
- [ ] Geração de SPED Fiscal
- [ ] Emissão de guias (DARF, GPS, DAS)
- [ ] Dashboard com métricas
- [ ] Alertas automáticos de prazos

## 💡 DICAS PRO

1. **Fale naturalmente**: O sistema entende português coloquial
2. **Envie múltiplos arquivos**: Analisa todos de uma vez
3. **Use o feedback**: 👍/👎 para melhorar respostas
4. **Aproveite sugestões**: Clique para aplicar automaticamente
5. **Grave áudio longo**: Sem limite de tempo

## 📞 SUPORTE

- Console do navegador (F12) para debug
- Logs do terminal do servidor
- Arquivo `contabil_agent.log`

## 📜 EXEMPLO DE RESPOSTA COMPLETA

**Entrada (áudio)**: "Preciso calcular férias de Maria, 1 ano de trabalho, salário 4 mil"

**Saída do Agente**:

```text
📊 CÁLCULO DE FÉRIAS - MARIA

Período aquisitivo: 12 meses completos
Salário base: R$ 4.000,00

📝 Cálculos:
├─ Férias (30 dias): R$ 4.000,00
├─ 1/3 Constitucional: R$ 1.333,33
├─ Total bruto: R$ 5.333,33
├─ INSS (11%): -R$ 586,67
└─ Total líquido: R$ 4.746,66

⚖️ Base Legal: Art. 130-144 CLT

📄 [PDF GERADO AUTOMATICAMENTE]
```

**Sugestões automáticas**:

- Calcular 13º salário proporcional
- Gerar recibo de férias
- Verificar saldo de férias vencidas

---

**Desenvolvido por Elite Sênior Consultoria**  
Versão 2.0.0 | Janeiro 2026
