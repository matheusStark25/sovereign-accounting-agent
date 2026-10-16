# Motor de Execução Robótica (RPA) - Documentação Técnica

## 📋 Visão Geral

O **executor_motor.py** é um motor de automação RPA de nível enterprise, desenvolvido com Playwright (Async) para executar processos contábeis de forma robusta, escalável e auditável.

## 🏗️ Arquitetura

### Componentes Principais

1. **AccountingBot**: Classe principal thread-safe para execução de automações
2. **SessionAuditoria**: Registro completo de cada execução
3. **ElementoMapeado**: Metadados de elementos da página

### Características Técnicas

## 🚀 Instalação

### Dependências

```bash
# Instalar Playwright
pip install playwright

# Instalar browsers
playwright install chromium
```

### Estrutura de Diretórios

```
contabil_agente/
├── tools/
│   ├── executor_motor.py          # Motor principal
│   ├── demo_executor_motor.py     # Exemplos de uso
│   ├── config_exemplo_login.json  # Config: Login
│   └── config_exemplo_nfe.json    # Config: Emissão NF-e
├── logs/
│   └── automacao/
│       ├── auditoria_*.json       # Relatórios de auditoria
│       ├── screenshots/           # Screenshots
│       ├── downloads/             # Arquivos baixados
│       └── erro_*.png             # Screenshots de erros
```

## 💻 Uso Básico

### Exemplo 1: Configuração Inline

```python
import asyncio
from tools.executor_motor import AccountingBot

async def main():
    # Configuração do fluxo
    config = {
        "nome": "Login no Sistema",
        "acoes": [
            {
                "tipo": "goto",
                "url": "https://sistema.com/login"
            },
            {
                "tipo": "fill",
                "selector": "#email",
                "value": "usuario@empresa.com"
            },
            {
                "tipo": "fill",
                "selector": "#senha",
                "value": "senha123"
            },
            {
                "tipo": "click",
                "selector": "button[type='submit']"
            },
            {
                "tipo": "wait",
                "selector": ".dashboard",
                "timeout": 10000
            },
            {
                "tipo": "screenshot",
                "path": "dashboard.png"
            }
        ]
    }
    
    # Criar bot
    bot = AccountingBot(headless=False)
    
    try:
        # Inicializar
        await bot.inicializar()
        
        # Executar fluxo
        sessao = await bot.executar_fluxo(
            config=config,
            tenant_id="EMPRESA-001"
        )
        
        # Verificar resultado
        print(f"Status: {sessao.status}")
        print(f"Ações: {sessao.acoes_sucesso}/{sessao.total_acoes}")
        
    finally:
        # Finalizar
        await bot.finalizar()

# Executar
asyncio.run(main())
```

### Exemplo 2: Carregar de Arquivo JSON

```python
from tools.executor_motor import executar_automacao_contabil
import asyncio

async def main():
    # Executar usando arquivo JSON
    sessao = await executar_automacao_contabil(
        config_path="tools/config_exemplo_login.json",
        tenant_id="EMPRESA-001",
        headless=False
    )
    
    print(f"Status: {sessao.status}")
    print(f"Screenshots: {sessao.screenshots}")

asyncio.run(main())
```

## 🎯 Ações Suportadas

### 1. `goto` - Navegação

```json
{
    "tipo": "goto",
    "url": "https://sistema.com",
    "timeout": 30000
}
```

### 2. `click` - Clique em Elemento

```json
{
    "tipo": "click",
    "selector": "#btn-login",
    "timeout": 5000
}
```

### 3. `fill` - Preenchimento de Campo

```json
{
    "tipo": "fill",
    "selector": "input[name='email']",
    "value": "usuario@empresa.com",
    "timeout": 5000
}
```

### 4. `wait` - Aguardar Elemento ou Tempo

```json
{
    "tipo": "wait",
    "selector": ".dashboard",
    "timeout": 10000
}
```

Ou aguardar tempo fixo:

```json
{
    "tipo": "wait",
    "tempo": 3000
}
```

### 5. `screenshot` - Captura de Tela

```json
{
    "tipo": "screenshot",
    "path": "pagina.png",
    "full_page": true
}
```

### 6. `download` - Download de Arquivo

```json
{
    "tipo": "download",
    "selector": "#btn-baixar-relatorio"
}
```

### 7. `press` - Pressionar Tecla

```json
{
    "tipo": "press",
    "selector": "#campo-cnpj",
    "key": "Tab"
}
```

### 8. `hover` - Passar Mouse

```json
{
    "tipo": "hover",
    "selector": "#menu-opcoes"
}
```

### 9. `select` - Selecionar Opção

```json
{
    "tipo": "select",
    "selector": "#tipo-operacao",
    "value": "venda"
}
```

## 🗺️ Mapeamento Inteligente de Páginas

```python
async def mapear_sistema():
    bot = AccountingBot(headless=False)
    
    try:
        await bot.inicializar()
        
        # Obter contexto e página
        contexto = await bot._obter_contexto("MAPPING-001")
        page = await contexto.new_page()
        
        # Navegar
        await page.goto("https://sistema.com/login")
        
        # Mapear página
        esquema = await bot.mapear_pagina_atual(page)
        
        # Salvar esquema
        import json
        with open("mapeamento_login.json", "w") as f:
            json.dump(esquema, f, indent=2, ensure_ascii=False)
        
        print(f"Elementos mapeados: {esquema['total_elementos']}")
        
        await page.close()
        
    finally:
        await bot.finalizar()

asyncio.run(mapear_sistema())
```

**Resultado do Mapeamento:**

```json
{
  "url": "https://sistema.com/login",
  "titulo": "Login - Sistema Contábil",
  "timestamp": "2026-02-04T10:30:00",
  "total_elementos": 15,
  "elementos": [
    {
      "tag": "input",
      "id": "email",
      "name": "email",
      "placeholder": "Digite seu e-mail",
      "seletores": {
        "css": "#email",
        "xpath": null
      },
      "estado": {
        "visivel": true,
        "habilitado": true
      }
    },
    {
      "tag": "button",
      "id": "btn-login",
      "text": "Entrar",
      "seletores": {
        "css": "#btn-login"
      },
      "estado": {
        "visivel": true,
        "habilitado": true
      }
    }
  ]
}
```

## 🔄 Retry Logic

O motor implementa retry automático com as seguintes características:

```python
# O retry é automático, mas pode ser configurado:
AccountingBot.MAX_RETRIES = 5  # 5 tentativas
AccountingBot.RETRY_DELAY = 3000  # 3 segundos
```

## 🔍 Tracing Visual

Elementos são automaticamente destacados antes de interações:

```python
# Customizar estilo de destaque
AccountingBot.HIGHLIGHT_STYLE = "border: 5px solid blue; box-shadow: 0 0 30px blue;"
```

## 📊 Auditoria e Logs

### Estrutura da Sessão de Auditoria

```json
{
  "tenant_id": "EMPRESA-001",
  "session_id": "session_EMPRESA-001_20260204_103000",
  "timestamp_inicio": "2026-02-04T10:30:00",
  "timestamp_fim": "2026-02-04T10:32:15",
  "duracao_segundos": 135.42,
  "total_acoes": 8,
  "acoes_sucesso": 7,
  "acoes_falha": 1,
  "taxa_sucesso": 87.5,
  "status": "concluido",
  "logs": [
    {
      "timestamp": "2026-02-04T10:30:05",
      "acao": "goto",
      "status": "sucesso",
      "detalhes": {"tentativa": 1}
    },
    {
      "timestamp": "2026-02-04T10:30:10",
      "acao": "fill",
      "status": "sucesso",
      "detalhes": {"tentativa": 1}
    }
  ],
  "screenshots": [
    "logs/automacao/screenshots/dashboard.png",
    "logs/automacao/screenshots/relatorios.png"
  ]
}
```

## 🏢 Multi-tenancy

Cada tenant tem contexto isolado:

```python
async def multi_tenant():
    bot = AccountingBot(headless=False)
    
    try:
        await bot.inicializar()
        
        # Executar para múltiplos tenants simultaneamente
        tenants = ["EMPRESA-A", "EMPRESA-B", "EMPRESA-C"]
        
        tarefas = [
            bot.executar_fluxo(config, tenant_id=tid)
            for tid in tenants
        ]
        
        # Executar em paralelo
        resultados = await asyncio.gather(*tarefas)
        
        for sessao in resultados:
            print(f"{sessao.tenant_id}: {sessao.status}")
        
    finally:
        await bot.finalizar()
```

## ⚠️ Gestão de Erros

### Captura Automática de Erros

Quando um erro ocorre:

1. **Screenshot automático**: `erro_[tenant]_[session]_[contexto]_[timestamp].png`
2. **HTML da página**: `erro_[tenant]_[session]_[contexto]_[timestamp].html`
3. **Log estruturado**: Adicionado à sessão de auditoria

### Ações Críticas vs Não-Críticas

```json
{
    "tipo": "click",
    "selector": "#botao-opcional",
    "critico": false
}
```

Se `critico: false`, a execução continua mesmo em caso de falha.

## 📝 Formato de Configuração JSON Completo

```json
{
  "nome": "Nome do Fluxo",
  "descricao": "Descrição detalhada",
  "versao": "1.0.0",
  "tenant_id": "TENANT-ID",
  "acoes": [
    {
      "tipo": "goto|click|fill|wait|screenshot|download|press|hover|select",
      "selector": "#elemento",
      "value": "valor",
      "url": "https://...",
      "timeout": 30000,
      "critico": true,
      "descricao": "Descrição da ação"
    }
  ],
  "metadata": {
    "autor": "Nome do Autor",
    "criado_em": "2026-02-04",
    "tags": ["tag1", "tag2"],
    "ambiente": "producao|homologacao|desenvolvimento"
  }
}
```

## 🔧 Configurações Avançadas

### Timeouts

```python
# Timeout padrão (30 segundos)
AccountingBot.TIMEOUT_PADRAO = 60000  # 60 segundos
```

### Diretórios Personalizados

```python
from pathlib import Path

bot = AccountingBot(
    headless=True,
    logs_dir=Path("meus_logs"),
    screenshots_dir=Path("minhas_capturas")
)
```

### Modo Headless

```python
# Modo headless (sem interface gráfica)
bot = AccountingBot(headless=True)

# Modo visual (com navegador visível)
bot = AccountingBot(headless=False)
```

## 📚 Exemplos de Casos de Uso

### 1. Login Automático

Ver: `config_exemplo_login.json`

### 2. Emissão de NF-e

Ver: `config_exemplo_nfe.json`

### 3. Extração de Relatórios

```json
{
  "nome": "Extração de Relatório Mensal",
  "acoes": [
    {"tipo": "goto", "url": "https://sistema.com/relatorios"},
    {"tipo": "select", "selector": "#periodo", "value": "mensal"},
    {"tipo": "select", "selector": "#mes", "value": "01"},
    {"tipo": "select", "selector": "#ano", "value": "2026"},
    {"tipo": "click", "selector": "#btn-gerar"},
    {"tipo": "wait", "selector": ".relatorio-pronto", "timeout": 60000},
    {"tipo": "download", "selector": "#btn-baixar-excel"}
  ]
}
```

## 🎓 Boas Práticas

1. **Use seletores CSS específicos**: Prefira IDs únicos
2. **Configure timeouts adequados**: Páginas lentas precisam de mais tempo
3. **Marque ações não-críticas**: Use `"critico": false` para ações opcionais
4. **Capture screenshots estratégicos**: Antes e depois de ações importantes
5. **Documente suas configurações**: Use campos `descricao` e `metadata`
6. **Valide antes de executar em produção**: Teste em modo `headless=False`
7. **Monitore logs de auditoria**: Revise sessões com falhas

## 🐛 Troubleshooting

### Erro: "Element not found"

**Solução**: Aumente o timeout ou verifique o seletor

```json
{
    "tipo": "wait",
    "selector": "#elemento",
    "timeout": 15000
}
```

### Erro: "Context closed"

**Solução**: Não reutilize contextos fechados, crie novo bot

### Browser não abre

**Solução**: Instale browsers do Playwright

```bash
playwright install chromium
```

## 📞 Suporte

Para questões técnicas, consulte:

**Desenvolvido por**: Principal Automation Engineer
**Data**: 2026-02-04
**Versão**: 1.0.0
