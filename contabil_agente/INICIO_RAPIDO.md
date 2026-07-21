# 🚀 GUIA DE INÍCIO RÁPIDO - ROGIO PRO CHAT INTERFACE

## ✅ O QUE FOI IMPLEMENTADO

### Frontend → Backend Integração Completa

✅ **API REST Integrada**

- Comunicação via `/api/chat` (POST)
- Health check via `/api/health` (GET)
- Download de PDFs via `/download/<filename>` (GET)
- Gerenciamento de sessões via `/api/session/<id>` (DELETE)

✅ **Gerenciamento de Sessão**

- UUID persistente no localStorage
- Contexto mantido entre conversas
- Recuperação automática de sessão

✅ **Processamento de Mensagens**

- Envio assíncrono com fetch API
- Indicadores visuais de processamento
- Tratamento robusto de erros
- Timeout configurável

✅ **Suporte a PDF**

- Download automático quando disponível
- Card visual de documento
- Botão de download integrado

✅ **Análise Técnica (Modo Profissional)**

- Card de "pensamento" da IA
- Mostra análise técnica antes da resposta
- Animações suaves

✅ **Multi-Perfil**

- Profissional: Analytics e detalhes técnicos
- Rural: Interface simplificada
- Idoso: Alto contraste e acessibilidade

✅ **Monitoramento**

- Status de conexão em tempo real
- Verificação periódica do servidor (30s)
- Indicadores visuais de status

---

## 📋 PRÉ-REQUISITOS

1. **Python 3.8+** instalado
2. **Chave da API Groq** (obtenha em <https://console.groq.com/keys>)
3. **Dependências instaladas** (veja requirements.txt)

---

## 🏃 COMO EXECUTAR

### Opção 1: Script PowerShell (Windows - RECOMENDADO)

```powershell
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"
.\start_rogio.ps1
```

### Opção 2: Script Python

```bash
cd contabil_agente
python start_rogio.py
```

### Opção 3: Direto pelo app.py

```bash
cd contabil_agente
python app.py
```

---

## ⚙️ CONFIGURAÇÃO

### 1. Criar arquivo .env

Copie o arquivo `.env.example` para `.env`:

```bash
copy .env.example .env
```

Ou no PowerShell:

```powershell
Copy-Item .env.example .env
```

### 2. Editar .env com sua chave Groq

```env
GROQ_API_KEY=gsk_sua_chave_aqui
PORT=5000
FLASK_DEBUG=False
```

### 3. Instalar dependências (se ainda não instalou)

```bash
pip install -r requirements.txt
```

---

## 🧪 TESTAR A INTEGRAÇÃO

Após iniciar o servidor, execute em outro terminal:

```bash
python test_integration.py
```

Este script testa:

- ✅ Servidor está rodando
- ✅ API health check responde
- ✅ API chat aceita requisições
- ✅ Frontend carrega corretamente

---

## 🌐 ACESSAR A INTERFACE

Depois de iniciar o servidor:

1. Abra o navegador
2. Acesse: **<http://localhost:5000>**
3. Teste os 3 perfis (botões no topo)
4. Envie uma mensagem de teste

---

## 📱 COMO USAR

### Trocar de Perfil

Clique nos botões no topo da tela:

- **👔 Profissional**: Interface técnica com analytics
- **🌾 Rural**: Interface simplificada
- **👴 Idoso**: Alto contraste, textos grandes

### Enviar Mensagens

1. Digite sua mensagem na caixa de texto
2. Pressione **Enter** ou clique no botão **🚀**
3. Aguarde a resposta (indicador de processamento aparecerá)

### Mensagens Rápidas (Quick Chips)

Clique nos botões de atalho abaixo da caixa de texto para enviar mensagens pré-definidas.

### Baixar PDFs

Quando um documento for gerado:

1. Um card de PDF aparecerá na conversa
2. Clique em **"Baixar PDF"** para fazer download

---

## 🔍 ENDPOINTS DA API

### POST /api/chat

Processa mensagens do chat

**Request:**

```json
{
  "mensagem": "Calcular INSS de R$ 5000",
  "session_id": "uuid-opcional"
}
```

**Response:**

```json
{
  "session_id": "uuid-gerado-ou-recebido",
  "resposta": "Texto da resposta...",
  "pensamento": "Análise técnica (opcional)...",
  "pdf_url": "/download/documento.pdf (opcional)",
  "contexto": { ... },
  "status": "sucesso",
  "timestamp": "2026-01-28T..."
}
```

### GET /api/health

Verifica saúde do servidor

**Response:**

```json
{
  "status": "online",
  "timestamp": "2026-01-28T...",
  "sessoes_ativas": 3,
  "modelo": "llama-3.3-70b-versatile"
}
```

### GET /download/{filename}

Baixa documento gerado

### DELETE /api/session/<session_id>

Encerra sessão específica

---

## 🎨 PERSONALIZAÇÃO

### Cores do Tema

Edite em `index_adapted.html`:

```css
:root {
  --accent-green: #2dce89;   /* Profissional */
  --accent-rural: #28a745;   /* Rural */
  --accent-idoso: #007bff;   /* Idoso */
}
```

### Mensagens Rápidas

Edite a função `updateContentForProfile()` em `index_adapted.html`:

```javascript
chips[0].textContent = "💰 Sua mensagem aqui";
```

### System Prompt da IA

Edite em `routes/chat.py` na seção de inicialização:

```python
from core.prompts import SYSTEM_PROMPT
system_prompt = SYSTEM_PROMPT
```

---

## 🔒 SEGURANÇA

✅ **Rate Limiting**

- 20 requisições/minuto por IP
- 200 requisições/dia por IP
- Bloqueio temporário em caso de abuso

✅ **Validação de Input**

- Sanitização automática
- Limite de 10.000 caracteres
- Validação de nomes de arquivo

✅ **Sessões Seguras**

- UUID v4 para session IDs
- Limpeza automática após 2 horas de inatividade

---

## 🐛 TROUBLESHOOTING

### Erro: "Módulo 'flask' não encontrado"

```bash
pip install flask flask-cors
```

### Erro: "GROQ_API_KEY não encontrada"

1. Verifique se o arquivo `.env` existe na pasta `contabil_agente`
2. Verifique se a chave está configurada: `GROQ_API_KEY=gsk_...`
3. Não inclua espaços ou aspas ao redor da chave

### Porta já em uso

Altere no `.env`:

```env
PORT=8000
```

### Mensagens não enviando

1. Verifique se o servidor está rodando
2. Abra o Console do navegador (F12 → Console)
3. Procure por erros de rede
4. Teste o health check: <http://localhost:5000/api/health>

### PDF não baixa

1. Verifique se a pasta `temp_docs` existe
2. Verifique permissões de escrita
3. Verifique logs do servidor

---

## 📂 ESTRUTURA DE ARQUIVOS

```plaintext
contabil_agente/
├── app.py                    # ✅ Servidor Flask principal (NOVO)
├── start_rogio.py            # ✅ Script de inicialização Python (NOVO)
├── start_rogio.ps1           # ✅ Script de inicialização PowerShell (NOVO)
├── test_integration.py       # ✅ Testes de integração (NOVO)
├── index_adapted.html        # ✅ Frontend integrado com backend (MODIFICADO)
├── ROGIO_INTERFACE_README.md # ✅ Documentação detalhada (NOVO)
├── .env.example              # ✅ Exemplo de configuração (NOVO)
├── .env                      # Suas configurações (CRIAR)
├── routes/
│   └── chat.py              # Blueprint de chat (JÁ EXISTIA)
├── temp_docs/               # PDFs gerados (criado automaticamente)
└── requirements.txt         # Dependências Python
```

---

## ✨ FEATURES IMPLEMENTADAS

### Frontend (index_adapted.html)

- ✅ Fetch API para comunicação assíncrona
- ✅ Gerenciamento de sessão com localStorage
- ✅ Indicadores visuais de processamento
- ✅ Card de "pensamento" da IA
- ✅ Suporte a download de PDF
- ✅ Tratamento robusto de erros
- ✅ Health check periódico
- ✅ Animações suaves
- ✅ Markdown básico (negrito, itálico)
- ✅ Multi-perfil responsivo

### Backend (app.py)

- ✅ Servidor Flask configurado
- ✅ CORS habilitado
- ✅ Registro de blueprint de chat
- ✅ Rota para servir index.html
- ✅ Rota para health check
- ✅ Logging configurado
- ✅ Verificação de GROQ_API_KEY

### API (routes/chat.py)

- ✅ Endpoint POST /api/chat
- ✅ Endpoint GET /api/health
- ✅ Endpoint GET `/download/<filename>`
- ✅ Endpoint DELETE `/api/session/<id>`
- ✅ Rate limiting avançado
- ✅ Geração de PDF profissional
- ✅ Memória de conversação
- ✅ Normalização de texto
- ✅ Sanitização de input

---

## 🎯 PRÓXIMOS PASSOS

1. **Inicie o servidor**

   ```bash
   python start_rogio.py
   ```

2. **Execute os testes**

   ```bash
   python test_integration.py
   ```

3. **Abra o navegador**

   ```text
   http://localhost:5000
   ```

4. **Teste os 3 perfis**
   - Profissional
   - Rural
   - Idoso

5. **Envie mensagens de teste**
   - "Calcular INSS de R$ 5000"
   - "Como declaro meus rendimentos?"
   - "Quais documentos preciso?"

---

## 📞 SUPORTE

Para problemas:

1. Verifique os logs do servidor no terminal
2. Abra o Console do navegador (F12)
3. Execute `python test_integration.py`
4. Verifique o arquivo `ROGIO_INTERFACE_README.md`

---

## ✅ CHECKLIST DE VERIFICAÇÃO

Antes de usar, verifique:

- [ ] Python 3.8+ instalado
- [ ] Arquivo `.env` criado com GROQ_API_KEY
- [ ] Dependências instaladas (`pip install -r requirements.txt`)
- [ ] Servidor iniciado sem erros
- [ ] Health check respondendo (<http://localhost:5000/api/health>)
- [ ] Interface carregando (<http://localhost:5000>)
- [ ] Mensagens sendo processadas corretamente

---

**🎉 Tudo pronto! Sua interface está totalmente integrada com o backend!**
