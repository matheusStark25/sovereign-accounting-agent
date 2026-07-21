# 🎯 GUIA COMPLETO - CONECTAR HTML COM BACKEND

## ✅ STATUS ATUAL

Seu projeto **JÁ ESTÁ CONFIGURADO** para comunicação entre frontend e backend!

### O que já está funcionando

- ✅ Backend Flask implementado em `app.py`
- ✅ Rotas da API configuradas em `routes/chat.py`
- ✅ Interface HTML adaptável em `index_adapted.html`
- ✅ Sistema de comunicação via fetch API
- ✅ Gerenciamento de sessões
- ✅ Geração de PDFs

## 🚀 COMO INICIAR

### Passo 1: Configurar a API Key do GROQ

1. **Obter a chave:**
   - Acesse: <https://console.groq.com/keys>
   - Faça login ou crie uma conta
   - Clique em "Create API Key"
   - Copie a chave gerada (começa com `gsk_`)

2. **Configurar no projeto:**

   ```powershell
   # Abra o arquivo .env
   notepad .env
   ```

3. **Substitua esta linha:**

   ```env
   GROQ_API_KEY=your_groq_api_key_here
   ```

   **Por:**

   ```env
   GROQ_API_KEY=gsk_sua_chave_real_aqui
   ```

4. **Salve o arquivo** (Ctrl+S)

### Passo 2: Iniciar o Servidor

```powershell
# Navegue até a pasta contabil_agente
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"

# Execute o script de inicialização
.\iniciar_servidor.ps1
```

**OU manualmente:**

```powershell
# Ativar ambiente virtual
..\venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt

# Iniciar servidor
python app.py
```

### Passo 3: Acessar a Interface

Abra seu navegador em:

```text
http://localhost:5000/adaptada
```

## 🔗 COMO A COMUNICAÇÃO FUNCIONA

### Frontend → Backend

#### 1. Enviar Mensagem

```javascript
// O HTML envia mensagens via POST para /api/chat
const response = await fetch("/api/chat", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    mensagem: message,
    session_id: getSessionId(),
  }),
});
```

#### 2. Receber Resposta

```javascript
const data = await response.json();
// data.resposta - Texto da resposta da IA
// data.pensamento - Raciocínio interno (modo profissional)
// data.pdf_url - URL do PDF se gerado
// data.session_id - ID da sessão
```

#### 3. Verificar Saúde do Servidor

```javascript
const response = await fetch("/api/health");
const data = await response.json();
// data.status === "online"
```

### Backend → Frontend

#### Rotas Disponíveis

| Rota | Método | Descrição |
| ------ | -------- | ----------- |
| `/api/chat` | POST | Processa mensagens do chat |
| `/api/health` | GET | Status do servidor |
| `/download/<filename>` | GET | Download de PDFs gerados |
| `/adaptada` | GET | Interface adaptável |

## 🎨 FUNCIONALIDADES DA INTERFACE

### Perfis Disponíveis

1. **👔 Profissional**
   - Design escuro e moderno
   - Mostra pensamento da IA
   - Informações técnicas completas

2. **🌾 Rural**
   - Interface clara e simples
   - Linguagem acessível
   - Alto contraste

3. **👴 Idoso**
   - Fontes grandes (1.2rem)
   - Botões espaçados
   - Navegação simplificada

### Recursos Automáticos

- ✅ **Sessões persistentes** - O histórico de conversa é mantido
- ✅ **Geração de PDFs** - Documentos oficiais quando necessário
- ✅ **Markdown básico** - Negrito e itálico nas respostas
- ✅ **Rate limiting** - 20 req/min, 200 req/dia por IP
- ✅ **Limpeza automática** - Sessões antigas são removidas

## 🔧 TESTANDO A CONEXÃO

### 1. Teste Rápido de Configuração

```powershell
.\testar_configuracao.ps1
```

### 2. Teste Manual

1. **Inicie o servidor**
2. **Abra o DevTools do navegador** (F12)
3. **Vá na aba Console**
4. **Digite uma mensagem no chat**
5. **Observe os logs:**

```text
Chamando API do backend...
Resposta recebida: {...}
```

### 3. Teste de Endpoints

```powershell
# Teste de saúde
curl http://localhost:5000/api/health

# Deve retornar:
# {"status":"online","timestamp":"...","sessoes_ativas":0,"modelo":"llama-3.3-70b-versatile"}
```

## ❗ SOLUÇÃO DE PROBLEMAS

### Erro: "Erro ao conectar com o servidor"

**Causa:** Servidor não está rodando

**Solução:**

```powershell
# Verifique se o servidor está ativo
netstat -ano | findstr :5000

# Se não estiver, inicie o servidor
.\iniciar_servidor.ps1
```

### Erro: "GROQ_API_KEY não encontrada"

**Causa:** Chave da API não configurada

**Solução:**

1. Abra `.env`
2. Verifique se a linha está assim:

   ```env
   GROQ_API_KEY=gsk_sua_chave_aqui
   ```

3. Reinicie o servidor

### Erro: "CORS policy error"

**Causa:** Flask-CORS não instalado

**Solução:**

```powershell
pip install flask-cors
```

### Status mostra "Offline"

**Causa:** Backend não está respondendo

**Verificação:**

1. Verifique se `http://localhost:5000/api/health` responde
2. Veja os logs no terminal do servidor
3. Verifique se a porta 5000 está livre

### PDF não está sendo gerado

**Causa:** ReportLab não instalado ou erro no processamento

**Solução:**

```powershell
pip install reportlab
```

## 📊 FLUXO COMPLETO DE UMA MENSAGEM

```text
1. Usuário digita mensagem
   ↓
2. JavaScript captura o envio
   ↓
3. Frontend envia POST para /api/chat
   ↓
4. Backend recebe e normaliza a mensagem
   ↓
5. Backend consulta GROQ API
   ↓
6. Backend processa resposta
   ↓
7. Backend gera PDF (se necessário)
   ↓
8. Backend retorna JSON com resposta
   ↓
9. Frontend recebe e exibe a mensagem
   ↓
10. Frontend adiciona botão de PDF (se disponível)
```

## 🎯 VERIFICAÇÃO FINAL

Execute este checklist:

- [ ] Arquivo `.env` configurado com GROQ_API_KEY válida
- [ ] Servidor iniciado com `.\iniciar_servidor.ps1`
- [ ] Navegador aberto em `http://localhost:5000/adaptada`
- [ ] Console do navegador sem erros (F12)
- [ ] Mensagem de teste enviada com sucesso
- [ ] Resposta da IA recebida
- [ ] Status mostra "Sistema Conectado ✓"

## 📝 EXEMPLOS DE USO

### Exemplo 1: Consulta Simples

```text
Usuário: "Como calcular férias?"
IA: [Resposta detalhada com base legal]
```

### Exemplo 2: Gerar Documento

```text
Usuário: "Preciso calcular rescisão de um funcionário com 2 anos de empresa, salário R$ 3000"
IA: [Cálculo detalhado]
Sistema: [Gera PDF automaticamente]
```

### Exemplo 3: Contexto Mantido

```text
Usuário: "Qual o prazo para pagamento?"
IA: "O prazo é de 10 dias..."
Usuário: "E se atrasar?"
IA: [Responde considerando a pergunta anterior]
```

## 🌐 PRÓXIMOS PASSOS

Após tudo funcionando:

1. **Personalize** - Ajuste cores, textos e branding
2. **Expanda** - Adicione novos tipos de documentos
3. **Monitore** - Acompanhe logs e uso
4. **Deploy** - Publique em servidor de produção

## 📞 SUPORTE

Logs importantes estão em:

- Console do terminal (servidor)
- DevTools do navegador (frontend)
- Arquivo `contabil_agent.log`

---

**🎉 Parabéns! Seu sistema está pronto para uso!**
