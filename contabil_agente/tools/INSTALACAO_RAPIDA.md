# 🚀 Guia Rápido de Instalação - Motor de Execução Robótica

## ⚡ Instalação em 3 Passos

### 1️⃣ Instalar Dependências

```bash
# Navegar para o diretório do projeto
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"

# Ativar ambiente virtual (se necessário)
..\venv\Scripts\activate

# Instalar dependências do motor RPA
pip install -r tools/requirements_executor.txt

# Instalar navegadores do Playwright
playwright install chromium
```

### 2️⃣ Verificar Instalação

```bash
# Executar teste básico
python tools/executor_motor.py
```

Você deve ver:
```
🤖 AccountingBot inicializado (headless=False)
📁 Logs: logs\automacao
📸 Screenshots: logs\automacao\screenshots
✅ Playwright inicializado com sucesso
```

### 3️⃣ Executar Demonstração Interativa

```bash
python tools/demo_executor_motor.py
```

Menu interativo aparecerá:
```
🤖 DEMONSTRAÇÃO DO MOTOR DE AUTOMAÇÃO CONTÁBIL
Escolha um exemplo para executar:

1. Uso Básico (configuração inline)
2. Carregar de Arquivo JSON
3. Mapeamento Inteligente de Página
4. Multi-tenancy (Múltiplos Tenants)
5. Retry Logic em Ação
6. Executar TODOS os exemplos
0. Sair
```

---

## 📂 Estrutura de Arquivos

```
contabil_agente/
├── tools/
│   ├── executor_motor.py              ⭐ Motor principal (900+ linhas)
│   ├── demo_executor_motor.py         📘 Exemplos de uso
│   ├── test_executor_motor.py         🧪 Testes unitários (50+ testes)
│   ├── config_exemplo_login.json      📋 Config: Login
│   ├── config_exemplo_nfe.json        📋 Config: Emissão NF-e
│   ├── requirements_executor.txt      📦 Dependências
│   └── README_EXECUTOR_MOTOR.md       📖 Documentação completa
├── logs/
│   └── automacao/
│       ├── auditoria_*.json           📊 Relatórios de auditoria
│       ├── screenshots/               📸 Capturas de tela
│       └── downloads/                 💾 Arquivos baixados
```

---

## 🧪 Executar Testes Unitários

```bash
# Testes básicos
pytest tools/test_executor_motor.py -v

# Com cobertura de código
pytest tools/test_executor_motor.py -v --cov=tools.executor_motor --cov-report=html

# Executar teste específico
pytest tools/test_executor_motor.py::test_sessao_auditoria_criacao -v

# Pular testes lentos
pytest tools/test_executor_motor.py -v -m "not slow"
```

---

## 📝 Uso Rápido - Código Mínimo

### Opção 1: Configuração Inline

```python
import asyncio
from tools.executor_motor import AccountingBot

async def main():
    bot = AccountingBot(headless=False)
    
    try:
        await bot.inicializar()
        
        config = {
            "nome": "Meu Primeiro Fluxo",
            "acoes": [
                {"tipo": "goto", "url": "https://example.com"},
                {"tipo": "screenshot", "path": "meu_teste.png"}
            ]
        }
        
        sessao = await bot.executar_fluxo(config, tenant_id="EMPRESA-001")
        print(f"✅ Status: {sessao.status}")
        
    finally:
        await bot.finalizar()

asyncio.run(main())
```

### Opção 2: Carregar de JSON

```python
import asyncio
from tools.executor_motor import executar_automacao_contabil

async def main():
    sessao = await executar_automacao_contabil(
        config_path="tools/config_exemplo_login.json",
        tenant_id="EMPRESA-001",
        headless=False
    )
    
    print(f"✅ Executado: {sessao.total_acoes} ações")
    print(f"📸 Screenshots: {len(sessao.screenshots)}")

asyncio.run(main())
```

---

## 🎯 Casos de Uso Prontos

### 1. Login Automático

```bash
# Editar config_exemplo_login.json com suas credenciais
# Executar:
python -c "
import asyncio
from tools.executor_motor import executar_automacao_contabil

async def run():
    await executar_automacao_contabil(
        'tools/config_exemplo_login.json',
        'EMPRESA-001',
        headless=False
    )

asyncio.run(run())
"
```

### 2. Emissão de NF-e

```bash
# Usar config_exemplo_nfe.json como template
# Customizar e executar
```

### 3. Mapear Página Web

```python
import asyncio
from tools.executor_motor import AccountingBot

async def mapear():
    bot = AccountingBot(headless=False)
    await bot.inicializar()
    
    contexto = await bot._obter_contexto("MAP-001")
    page = await contexto.new_page()
    await page.goto("https://sistema-contabil.com/login")
    
    esquema = await bot.mapear_pagina_atual(page)
    
    import json
    print(json.dumps(esquema, indent=2, ensure_ascii=False))
    
    await page.close()
    await bot.finalizar()

asyncio.run(mapear())
```

---

## 🔧 Configuração Avançada

### Customizar Timeouts

```python
from tools.executor_motor import AccountingBot

# Aumentar timeout padrão para 60 segundos
AccountingBot.TIMEOUT_PADRAO = 60000

# Aumentar número de retries para 5
AccountingBot.MAX_RETRIES = 5

bot = AccountingBot(headless=True)
```

### Customizar Diretórios

```python
from pathlib import Path
from tools.executor_motor import AccountingBot

bot = AccountingBot(
    headless=True,
    logs_dir=Path("C:/Logs/RPA"),
    screenshots_dir=Path("C:/Screenshots/RPA")
)
```

### Modo Debug

```python
import logging

# Ativar logs de debug
logging.getLogger("tools.executor_motor").setLevel(logging.DEBUG)

# Ou para ver TUDO
logging.basicConfig(level=logging.DEBUG)
```

---

## ⚠️ Troubleshooting

### Erro: "playwright: command not found"

```bash
# Reinstalar Playwright
pip uninstall playwright
pip install playwright
playwright install chromium
```

### Erro: "Browser not found"

```bash
# Instalar todos os browsers
playwright install

# Ou apenas Chromium
playwright install chromium
```

### Erro: "Permission denied" em logs/

```bash
# Windows: Dar permissão de escrita
icacls logs /grant Users:F /T

# Ou executar como Administrador
```

### Página não carrega (timeout)

```python
# Aumentar timeout na ação específica
{
    "tipo": "goto",
    "url": "https://site-lento.com",
    "timeout": 60000  # 60 segundos
}
```

### Elemento não encontrado

```python
# 1. Usar wait antes do click
{
    "tipo": "wait",
    "selector": "#elemento",
    "timeout": 15000
},
{
    "tipo": "click",
    "selector": "#elemento"
}

# 2. Capturar screenshot para debugar
{
    "tipo": "screenshot",
    "path": "debug_elemento.png",
    "full_page": true
}
```

---

## 📊 Visualizar Logs de Auditoria

```python
import json
from pathlib import Path

# Listar auditorias
auditorias = list(Path("logs/automacao").glob("auditoria_*.json"))

# Abrir última auditoria
ultima = sorted(auditorias)[-1]
with open(ultima, "r", encoding="utf-8") as f:
    data = json.load(f)

# Exibir resumo
print(f"Tenant: {data['tenant_id']}")
print(f"Status: {data['status']}")
print(f"Ações: {data['total_acoes']}")
print(f"Taxa de sucesso: {data['taxa_sucesso']}%")

# Exibir logs
for log in data['logs']:
    print(f"[{log['timestamp']}] {log['acao']}: {log['status']}")
```

---

## 🚀 Próximos Passos

1. **Customizar Configurações**: Edite `config_exemplo_login.json` com seus sistemas
2. **Criar Novos Fluxos**: Use os exemplos como template
3. **Integrar com API**: Chame o motor via endpoints REST
4. **Agendar Execuções**: Use Windows Task Scheduler ou Cron
5. **Monitorar Logs**: Configure alertas para falhas

---

## 💡 Dicas de Performance

1. **Use headless=True em produção** (mais rápido)
2. **Configure timeouts apropriados** (não muito curtos nem longos)
3. **Marque ações não-críticas** com `"critico": false`
4. **Capture screenshots estratégicos** (não em todas as ações)
5. **Reutilize contextos** para múltiplas páginas do mesmo tenant

---

## 📞 Suporte

- **Documentação Completa**: `tools/README_EXECUTOR_MOTOR.md`
- **Exemplos**: `tools/demo_executor_motor.py`
- **Testes**: `tools/test_executor_motor.py`
- **Playwright Docs**: https://playwright.dev/python/

---

## ✅ Checklist de Validação

Marque conforme completa:

- [ ] Playwright instalado (`pip install playwright`)
- [ ] Navegadores instalados (`playwright install chromium`)
- [ ] Teste básico executado (`python tools/executor_motor.py`)
- [ ] Demo interativa testada (`python tools/demo_executor_motor.py`)
- [ ] Testes unitários passando (`pytest tools/test_executor_motor.py`)
- [ ] Config personalizada criada
- [ ] Primeiro fluxo executado com sucesso
- [ ] Logs de auditoria verificados

---

**Pronto! Você está apto para automatizar processos contábeis! 🎉**
