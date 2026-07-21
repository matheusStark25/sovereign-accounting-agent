# 🤖 ROGIO PRO - Interface Adaptável

> Sistema de Chat Contábil Inteligente com 3 Perfis de Interface

## 🎯 O QUE É?

Interface web inteligente que se comunica com um backend Flask/GROQ para fornecer assistência contábil especializada. A interface possui 3 perfis adaptáveis:

- **👔 Profissional** - Design moderno e técnico
- **🌾 Rural** - Interface clara e simples  
- **👴 Idoso** - Alto contraste e fontes grandes

## ⚡ INÍCIO RÁPIDO (3 PASSOS)

### 1. Configure a API Key

```powershell
# 1.1 Obtenha sua chave em: https://console.groq.com/keys
# 1.2 Edite o arquivo .env
notepad .env

# 1.3 Cole sua chave:
GROQ_API_KEY=gsk_sua_chave_aqui
```

### 2. Inicie o Servidor

```powershell
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"
.\iniciar_servidor.ps1
```

### 3. Acesse a Interface

Abra: **<http://localhost:5000/adaptada>**

## ✅ ESTÁ FUNCIONANDO?

Verifique se:

- ✅ Status mostra "Sistema Conectado ✓" (verde)
- ✅ Você consegue enviar mensagens
- ✅ A IA responde em poucos segundos
- ✅ Pode trocar entre perfis

## 🔧 SOLUÇÃO DE PROBLEMAS

### Servidor não inicia?

```powershell
.\diagnosticar.ps1
```

### API Key não configurada?

```powershell
# Copie o exemplo
Copy-Item .env.example .env

# Edite e cole sua chave
notepad .env
```

### Porta 5000 ocupada?

```powershell
# Edite .env e mude a porta
notepad .env
# Altere: PORT=5001
```

## 📚 DOCUMENTAÇÃO COMPLETA

| Arquivo | Descrição |
| --------- | ----------- |
| [LEIA_PRIMEIRO.txt](LEIA_PRIMEIRO.txt) | 📄 Resumo visual completo |
| [CHECKLIST_SETUP.md](CHECKLIST_SETUP.md) | ✅ Passo a passo detalhado |
| [CONEXAO_COMPLETA.md](CONEXAO_COMPLETA.md) | 🔗 Guia técnico de conexão |
| [INSTALACAO_RAPIDA.md](INSTALACAO_RAPIDA.md) | ⚡ Setup em 3 minutos |
| [diagnosticar.ps1](diagnosticar.ps1) | 🔍 Script de diagnóstico |

## 🎨 RECURSOS

- ✅ Chat em tempo real com IA (GROQ)
- ✅ 3 perfis de interface adaptáveis
- ✅ Geração automática de PDFs
- ✅ Histórico de conversas
- ✅ Rate limiting (segurança)
- ✅ Markdown básico
- ✅ Sistema de sessões
- ✅ Health check endpoint

## 🏗️ ARQUITETURA

```text
┌─────────────────┐         ┌──────────────────┐
│                 │         │                  │
│  Frontend       │ ──────> │   Backend        │
│  (HTML/JS)      │  HTTP   │   (Flask)        │
│                 │ <────── │                  │
└─────────────────┘  JSON   └──────────────────┘
                                     │
                                     │ API
                                     ▼
                            ┌──────────────────┐
                            │                  │
                            │   GROQ API       │
                            │   (llama-3.3)    │
                            │                  │
                            └──────────────────┘
```

## 🔗 ENDPOINTS DA API

| Endpoint | Método | Descrição |
| ---------- | -------- | ----------- |
| `/api/chat` | POST | Processa mensagens |
| `/api/health` | GET | Status do servidor |
| `/download/<file>` | GET | Download de PDFs |
| `/adaptada` | GET | Interface principal |

## 🔒 SEGURANÇA

- **Rate Limiting**: 20 req/min, 200 req/dia por IP
- **Tamanho máximo**: 10.000 caracteres por mensagem
- **PDFs**: Expiram em 24 horas
- **Sessões**: Limpeza automática após 2 horas
- **Sanitização**: Nomes de arquivo validados

## 📦 ESTRUTURA DE ARQUIVOS

```text
contabil_agente/
├── app.py                    # 🚀 Servidor Flask
├── routes/
│   └── chat.py              # 💬 API de chat
├── index_adapted.html       # 🎨 Interface adaptável
├── .env                     # 🔐 Configurações
├── iniciar_servidor.ps1     # ▶️  Script de início
├── diagnosticar.ps1         # 🔍 Diagnóstico
├── testar_configuracao.ps1  # ✅ Teste de setup
└── requirements.txt         # 📦 Dependências
```

## 💡 EXEMPLOS DE USO

### Consulta Simples

```text
👤 Usuário: Como calcular férias?
🤖 Rogio: [Resposta com base legal e exemplos]
```

### Gerar Documento

```text
👤 Usuário: Calcule rescisão de funcionário com 2 anos, 
            salário R$ 3.000
🤖 Rogio: [Cálculo detalhado]
📄 Sistema: [PDF gerado automaticamente]
```

### Conversa Contextual

```text
👤 Usuário: Qual o prazo para pagamento de férias?
🤖 Rogio: O prazo é de até 2 dias antes do início...
👤 Usuário: E se atrasar?
🤖 Rogio: [Responde considerando contexto anterior]
```

## 🛠️ COMANDOS ÚTEIS

```powershell
# Testar configuração
.\testar_configuracao.ps1

# Diagnosticar problemas
.\diagnosticar.ps1

# Iniciar servidor
.\iniciar_servidor.ps1

# Verificar saúde
curl http://localhost:5000/api/health

# Ver porta em uso
netstat -ano | findstr :5000

# Instalar dependências
pip install -r requirements.txt
```

## 🎓 TECNOLOGIAS

- **Backend**: Flask 2.3.3
- **IA**: GROQ (llama-3.3-70b-versatile)
- **PDF**: ReportLab 4.0.4
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **CORS**: Flask-CORS 4.0.0

## 📊 REQUISITOS DO SISTEMA

- **Python**: 3.8 ou superior
- **RAM**: Mínimo 512MB disponível
- **Disco**: ~100MB para dependências
- **Internet**: Necessária para API GROQ
- **Navegador**: Chrome, Edge, Firefox (versão recente)

## 🚀 PRÓXIMOS PASSOS

Após configuração completa:

1. **Personalize** - Ajuste cores e branding em `index_adapted.html`
2. **Expanda** - Adicione novos tipos de documentos
3. **Integre** - Conecte com banco de dados
4. **Deploy** - Publique em servidor de produção

## 📞 SUPORTE

### Logs e Debug

- Console do navegador (F12)
- Terminal do servidor
- Arquivo `contabil_agent.log`

### Problemas Comuns

| Problema | Solução |
| ---------- | --------- |
| Servidor não inicia | Execute `diagnosticar.ps1` |
| API Key inválida | Verifique `.env` e console.groq.com |
| Interface não carrega | Confirme URL: localhost:5000/adaptada |
| Mensagens sem resposta | Veja logs no terminal do servidor |
| PDF não gera | Instale: `pip install reportlab` |

## 📜 LICENÇA

Este projeto é proprietário da Elite Sênior Consultoria.

## 👥 DESENVOLVIDO POR

**Elite Sênior Consultoria**  
Versão 1.0.0 | Janeiro 2026

---

## 🎯 RESUMO RÁPIDO

```powershell
# 1. Configure API Key
notepad .env
# Cole: GROQ_API_KEY=gsk_sua_chave

# 2. Inicie
.\iniciar_servidor.ps1

# 3. Acesse
# http://localhost:5000/adaptada

# 4. Use!
# Escolha perfil, digite mensagem, receba resposta!
```

---

**Precisa de ajuda? Execute: `.\diagnosticar.ps1`**
