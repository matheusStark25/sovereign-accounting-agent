# ✅ CHECKLIST DE CONFIGURAÇÃO - ROGIO PRO

Siga este checklist passo a passo para colocar o sistema em funcionamento:

## 📋 PRÉ-REQUISITOS

- [ ] Python 3.8+ instalado
- [ ] PowerShell disponível
- [ ] Navegador moderno (Chrome, Edge, Firefox)
- [ ] Acesso à internet (para API GROQ)

## 🔧 CONFIGURAÇÃO INICIAL

### Passo 1: Ambiente Virtual

```powershell
cd "c:\Users\User\Desktop\agent projeto V2"
```

- [ ] Ambiente virtual já existe em `venv\` ✅
- [ ] Se não existir, criar com: `python -m venv venv`

### Passo 2: Obter API Key do GROQ

1. - [ ] Acessar <https://console.groq.com/keys>
2. - [ ] Fazer login ou criar conta
3. - [ ] Clicar em "Create API Key"
4. - [ ] Dar um nome (ex: "Rogio Pro")
5. - [ ] Copiar a chave (começa com `gsk_`)

### Passo 3: Configurar API Key

```powershell
cd contabil_agente
notepad .env
```

- [ ] Arquivo `.env` aberto no Notepad
- [ ] Localizar linha: `GROQ_API_KEY=your_groq_api_key_here`
- [ ] Substituir por: `GROQ_API_KEY=gsk_sua_chave_copiada_aqui`
- [ ] Salvar arquivo (Ctrl+S)
- [ ] Fechar Notepad

**⚠️ IMPORTANTE:** Não compartilhe esta chave com ninguém!

## 🚀 INICIALIZAÇÃO

### Passo 4: Testar Configuração (Opcional mas Recomendado)

```powershell
.\testar_configuracao.ps1
```

- [ ] Script executado
- [ ] Todos os checks mostraram ✅ ou ⚠️ (warnings aceitáveis)
- [ ] Nenhum erro ❌ crítico

### Passo 5: Iniciar o Servidor

```powershell
.\iniciar_servidor.ps1
```

Verifique se aparecem as seguintes mensagens:

- [ ] "✅ Configuração OK"
- [ ] "📚 Verificando dependências..."
- [ ] "🌐 Iniciando servidor..."
- [ ] "Running on <http://0.0.0.0:5000>"

**⚠️ NÃO FECHE esta janela do PowerShell!**

## 🌐 TESTE DA INTERFACE

### Passo 6: Acessar no Navegador

- [ ] Abrir navegador
- [ ] Navegar para: `http://localhost:5000/adaptada`
- [ ] Interface carregou corretamente
- [ ] No canto superior direito, ver botões: `👔 Profissional`, `🌾 Rural`, `👴 Idoso`

### Passo 7: Verificar Conexão

- [ ] Abrir DevTools do navegador (pressionar F12)
- [ ] Ir na aba "Console"
- [ ] Verificar logs:

   ```text
   🚀 Rogio Pro Interface Iniciada
   📋 Session ID: [um UUID]
   💚 Health check: {status: "online", ...}
   ✅ Interface pronta para uso!
   ```

No header do chat:

- [ ] Status mostra: "Sistema Conectado ✓" (verde)

### Passo 8: Teste de Mensagem

1. - [ ] Digitar no chat: "Olá, você está funcionando?"
2. - [ ] Pressionar Enter ou clicar no 🚀
3. - [ ] Mensagem aparece no chat (lado direito, cinza escuro)
4. - [ ] Aparece card de status: "[Processando sua solicitação...]"
5. - [ ] Resposta da IA aparece (lado esquerdo, cinza claro)

**No Console (F12):**

- [ ] Ver logs:

   ```text
   📤 Enviando mensagem para backend: {...}
   📡 Resposta HTTP: 200 OK
   📥 Dados recebidos: {...}
   ```

## 🎨 TESTE DE PERFIS

### Passo 9: Testar Troca de Perfis

**Perfil Rural:**

- [ ] Clicar em `🌾 Rural`
- [ ] Interface ficou clara (fundo branco)
- [ ] Sidebar ficou branca
- [ ] Botões maiores e mais espaçados

**Perfil Idoso:**

- [ ] Clicar em `👴 Idoso`
- [ ] Fontes ficaram MUITO maiores
- [ ] Alto contraste (preto e branco)
- [ ] Bordas mais grossas

**Voltar ao Profissional:**

- [ ] Clicar em `👔 Profissional`
- [ ] Tema escuro retornou

## 📄 TESTE DE GERAÇÃO DE PDF

### Passo 10: Gerar um Documento

1. - [ ] Enviar mensagem: "Calcule férias de um funcionário com 12 meses de empresa, salário R$ 3000"
2. - [ ] Aguardar resposta da IA
3. - [ ] Verificar se aparece card de PDF com:
   - Ícone 📄
   - "Documento Oficial Gerado"
   - Botão "Baixar PDF"
4. - [ ] Clicar em "Baixar PDF"
5. - [ ] PDF baixado e abre corretamente

## ✅ VERIFICAÇÃO FINAL

Se TODOS os itens acima foram marcados, seu sistema está funcionando perfeitamente!

## 🔍 DIAGNÓSTICO DE PROBLEMAS

### Se a interface não carrega

1. Verificar se servidor está rodando:

   ```powershell
   netstat -ano | findstr :5000
   ```

   - [ ] Retorna uma linha com `:5000` e `LISTENING`

2. Testar endpoint de saúde:

   ```powershell
   curl http://localhost:5000/api/health
   ```

   - [ ] Retorna: `{"status":"online",...}`

### Se aparece erro de API Key

1. - [ ] Verificar arquivo `.env` tem a chave correta
2. - [ ] Chave começa com `gsk_`
3. - [ ] Não há espaços extras
4. - [ ] Reiniciar o servidor (Ctrl+C e executar novamente)

### Se mensagens não são enviadas

1. - [ ] Verificar Console do navegador (F12)
2. - [ ] Procurar por erros em vermelho
3. - [ ] Verificar se há erro CORS
4. - [ ] Confirmar que servidor está rodando

### Se PDF não gera

1. - [ ] Verificar logs do servidor no PowerShell
2. - [ ] Confirmar que ReportLab está instalado:

   ```powershell
   pip show reportlab
   ```

## 📞 AJUDA ADICIONAL

Documentação completa disponível em:

- `CONEXAO_COMPLETA.md` - Guia técnico detalhado
- `INSTALACAO_RAPIDA.md` - Setup rápido
- `COMO_INICIAR.md` - Instruções passo a passo
- `LEIA_PRIMEIRO.txt` - Resumo visual

## 🎉 SUCESSO

Se você chegou até aqui com todos os checks marcados:

```text
╔═══════════════════════════════════════════════════════╗
║                                                       ║
║  🎊 PARABÉNS! SEU SISTEMA ESTÁ FUNCIONANDO! 🎊        ║
║                                                       ║
║  Você agora tem acesso a:                             ║
║  ✅ Chat inteligente com IA                           ║
║  ✅ 3 perfis de interface                             ║
║  ✅ Geração automática de PDFs                        ║
║  ✅ Histórico de conversas                            ║
║                                                       ║
║  Aproveite o Rogio Pro! 🚀                            ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
```

---

Data da configuração: ________________

## Notas adicionais

---
---
