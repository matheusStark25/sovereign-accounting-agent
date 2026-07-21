# 🔄 Guia de Migração - Modular OOP

## Status Atual

✅ **Criado (Pronto para Uso):**
- `core/config.py` - Configuração centralizada
- `core/database.py` - Pool de conexões SQLite
- `core/security.py` - Sanitização e circuit breaker
- `tools/calculo_tool.py` - **Cálculos INSS/IRRF 2026**
- `utils/audit.py` - Sistema de auditoria
- `utils/helpers.py` - Funções auxiliares
- `utils/evolution.py` - Gerenciamento de evolução

⏳ **Pendente (Próxima Etapa):**
- `tools/rescisao_tool.py` - Rescisões completas
- `tools/pdf_tool.py` - Geração de PDFs
- `tools/assinatura_tool.py` - Assinaturas digitais
- `tools/voz_tool.py` - STT/TTS
- `tools/encargos_tool.py` - Encargos patronais
- `tools/prolabore_tool.py` - Pró-labore
- `tools/gps_tool.py` - Guias GPS
- `tools/darf_tool.py` - Guias DARF
- `tools/admissao_tool.py` - Admissões
- `orchestrator/dispatcher.py` - Detecção de intenção
- `orchestrator/main.py` - Orquestrador principal

---

## 🚀 Como Migrar o Código Existente

### Passo 1: Importações no `agent_contabil.py`

**ANTES (Monolítico):**
```python
# Tudo definido no mesmo arquivo
class ToolCalculo:
    def __init__(self):
        # ...
```

**DEPOIS (Modular):**
```python
# No topo do agent_contabil.py
from contabil_agente.core.config import Config
from contabil_agente.core.database import DatabasePool, TableCache
from contabil_agente.core.security import sanitizar_input, CircuitBreaker
from contabil_agente.tools.calculo_tool import ToolCalculo, DadosFuncionario, DadosRescisaoCalculo
from contabil_agente.utils.audit import send_audit, register_document_hash_in_governance
from contabil_agente.utils.helpers import _ensure_resposta_str
from contabil_agente.utils.evolution import EvolutionManager, CalculationLogger
```

### Passo 2: Remover Definições Duplicadas

**Procure e DELETE no `agent_contabil.py`:**
- `class ToolCalculo:` (linhas ~900-3000) - **JÁ ESTÁ EM tools/calculo_tool.py**
- Funções `send_audit()`, `register_document_hash_in_governance()` - **JÁ ESTÃO EM utils/audit.py**
- Função `_ensure_resposta_str()` - **JÁ ESTÁ EM utils/helpers.py**
- Classes `EvolutionManager`, `CalculationLogger` - **JÁ ESTÃO EM utils/evolution.py**

### Passo 3: Atualizar Instanciações

**ANTES:**
```python
calc_tool = ToolCalculo()  # Usa classe local
```

**DEPOIS:**
```python
from contabil_agente.tools.calculo_tool import ToolCalculo
calc_tool = ToolCalculo()  # Usa classe modular
```

### Passo 4: Configuração Centralizada

**ANTES:**
```python
SECRET_KEY = os.getenv("SECRET_KEY", "sua-chave-secreta")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DOCUMENTS_DIR = "contabil_agente/documents"
```

**DEPOIS:**
```python
from contabil_agente.core.config import Config

Config.validate()  # Cria diretórios automaticamente
# Usa Config.SECRET_KEY, Config.GROQ_API_KEY, Config.DOCUMENTS_DIR...
```

### Passo 5: Database Pool

**ANTES:**
```python
import sqlite3
conn = sqlite3.connect("database/dp.db")
```

**DEPOIS:**
```python
from contabil_agente.core.database import DatabasePool

pool = DatabasePool()
conn = pool.get_connection()
try:
    cursor = conn.cursor()
    cursor.execute("SELECT ...")
    # ...
finally:
    pool.return_connection(conn)
```

### Passo 6: Auditoria

**ANTES:**
```python
# Logs espalhados no código
print(f"Calculando INSS para {valor}")
```

**DEPOIS:**
```python
from contabil_agente.utils.audit import send_audit

send_audit(
    f"Calculando INSS para {valor}",
    level="info",
    context={"valor": float(valor), "usuario": usuario_id}
)
```

---

## 📋 Checklist de Migração

### Fase 1: Core e Utils (✅ COMPLETO)
- [x] Criar `core/config.py`
- [x] Criar `core/database.py`
- [x] Criar `core/security.py`
- [x] Criar `utils/audit.py`
- [x] Criar `utils/helpers.py`
- [x] Criar `utils/evolution.py`

### Fase 2: Ferramenta Crítica (✅ COMPLETO)
- [x] Criar `tools/calculo_tool.py` com lógica INSS/IRRF 2026
- [x] Validar preservação 100% dos cálculos

### Fase 3: Ferramentas Restantes (⏳ PRÓXIMO)
- [ ] Criar `tools/rescisao_tool.py`
- [ ] Criar `tools/pdf_tool.py`
- [ ] Criar `tools/assinatura_tool.py`
- [ ] Criar `tools/voz_tool.py`
- [ ] Criar `tools/encargos_tool.py`
- [ ] Criar `tools/prolabore_tool.py`
- [ ] Criar `tools/gps_tool.py`
- [ ] Criar `tools/darf_tool.py`
- [ ] Criar `tools/admissao_tool.py`

### Fase 4: Orquestrador (⏳ DEPOIS)
- [ ] Criar `orchestrator/dispatcher.py`
- [ ] Criar `orchestrator/main.py`

### Fase 5: Integração (⏳ FINAL)
- [ ] Atualizar `agent_contabil.py` com imports
- [ ] Remover código duplicado
- [ ] Testar rotas Flask
- [ ] Validar SocketIO
- [ ] Verificar cálculos end-to-end

---

## 🧪 Como Testar

### Teste Unitário (Módulo Isolado)
```python
# teste_modular.py
from contabil_agente.tools.calculo_tool import ToolCalculo
from decimal import Decimal

calc = ToolCalculo()

# Testa INSS
inss = calc.calcular_inss(Decimal("5000"))
print(f"INSS R$ 5.000,00 = R$ {inss:,.2f}")

# Testa IRRF
irrf = calc.calcular_irrf(Decimal("4500"))
print(f"IRRF R$ 4.500,00 = R$ {irrf:,.2f}")

# Esperado: Valores conforme tabela 2026
```

### Teste de Integração (Via Flask)
```bash
# Terminal 1: Inicia servidor
python agent_contabil.py

# Terminal 2: Testa endpoint
curl -X POST http://localhost:5002/api/calculo \
  -H "Content-Type: application/json" \
  -d '{"salario": 5000}'
```

### Teste de Rescisão Completa
```python
# Use exemplos_modular.py
python contabil_agente/exemplos_modular.py
```

---

## ⚠️ Pontos de Atenção

### 1. **INSS/IRRF 2026**
- ✅ Lógica preservada 100% em `tools/calculo_tool.py`
- ⚠️ NÃO modifique tabelas ou cálculos progressivos
- ℹ️ Atualização automática via scheduler (2h da manhã)

### 2. **Auditoria**
- Todos os métodos devem chamar `send_audit()` no início/fim
- Logs em `logs/evolucao_sistema.json` (últimos 5000 eventos)
- Dashboard real-time via SocketIO

### 3. **Thread Safety**
- DatabasePool usa locks para conexões
- EvolutionManager usa locks para escrita de logs
- TTS/STT em `tools/voz_tool.py` precisa lock (global TTS_LOCK)

### 4. **Backward Compatibility**
- Nomes de classes/métodos iguais aos originais
- Signatures de funções preservadas
- Rotas Flask inalteradas

---

## 🎯 Próximos Passos

1. **Execute exemplos:**
   ```bash
   python contabil_agente/exemplos_modular.py
   ```

2. **Revise documentação:**
   - Leia `MODULAR_README.md` para arquitetura completa
   - Veja exemplos em cada ferramenta criada

3. **Continue refatoração:**
   - Crie as 9 ferramentas restantes
   - Extraia orquestrador
   - Atualize `agent_contabil.py`

4. **Teste end-to-end:**
   - Rescisão completa (sem justa causa)
   - Geração de PDF (TRCT)
   - Assinatura digital
   - Cálculo com dependentes IRRF

---

## 📞 Suporte

Se encontrar erros durante a migração:

1. **Verifique imports:**
   ```python
   # Deve funcionar sem erros
   from contabil_agente.tools.calculo_tool import ToolCalculo
   ```

2. **Confirme estrutura:**
   ```
   contabil_agente/
   ├── core/
   │   ├── __init__.py
   │   ├── config.py
   │   ├── database.py
   │   └── security.py
   ├── tools/
   │   ├── __init__.py (existente)
   │   └── calculo_tool.py
   └── utils/
       ├── __init__.py
       ├── audit.py
       ├── helpers.py
       └── evolution.py
   ```

3. **Teste isolado:**
   ```bash
   python -c "from contabil_agente.core.config import Config; Config.validate(); print('OK')"
   ```

---

**✨ Benefícios Imediatos:**
- ✅ VS Code não trava mais (arquivos < 1.500 linhas)
- ✅ Testes unitários possíveis
- ✅ Manutenção facilitada
- ✅ Reutilização de código
- ✅ Auditoria centralizada
