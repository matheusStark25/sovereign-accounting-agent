# ⚠️ IMPORTANTE: Compatibilidade Python 3.14

## 🐛 Problema Identificado

O Playwright (e sua dependência `greenlet`) têm um **problema de compatibilidade conhecido com Python 3.14 no Windows**.

**Erro típico**:
```
ImportError: DLL load failed while importing _greenlet: 
Não foi possível encontrar o módulo especificado.
```

---

## ✅ Soluções Disponíveis

### Opção 1: Usar Python 3.11 ou 3.12 (RECOMENDADO)

```bash
# Instalar Python 3.12 (versão estável mais recente suportada)
# Download: https://www.python.org/downloads/

# Criar ambiente virtual com Python 3.12
py -3.12 -m venv venv_312

# Ativar ambiente
.\venv_312\Scripts\activate

# Instalar dependências
pip install -r tools/requirements_executor.txt
playwright install chromium

# Testar
python tools/validar_executor_motor.py
```

### Opção 2: Aguardar correção do greenlet

O issue está sendo tratado em:

- https://github.com/python-greenlet/greenlet/issues/400
- https://github.com/microsoft/playwright-python/issues/2370

**Timeline estimado**: greenlet 4.0+ com suporte a Python 3.14

### Opção 3: Usar alternativa Selenium (não recomendado)

Se precisar usar Python 3.14 imediatamente, considere Selenium:

```bash
pip install selenium
```

Mas note que **o código do executor_motor.py foi desenvolvido para Playwright** e precisaria ser reescrito.

---

## 🔍 Verificar sua versão do Python

```bash
python --version
```

**Versões suportadas atualmente**:

- ✅ Python 3.9
- ✅ Python 3.10  
- ✅ Python 3.11
- ✅ Python 3.12
- ❌ Python 3.14 (greenlet incompatível no Windows)

---

## 🚀 Instalação Correta (Python 3.12)

```bash
# 1. Criar ambiente dedicado
py -3.12 -m venv venv_rpa

# 2. Ativar
.\venv_rpa\Scripts\activate

# 3. Verificar versão
python --version  # Deve mostrar 3.12.x

# 4. Instalar dependências
pip install -r tools/requirements_executor.txt

# 5. Instalar browsers
playwright install chromium

# 6. Validar
python tools/validar_executor_motor.py

# 7. Testar
python tools/demo_executor_motor.py
```

---

## 📝 Resumo

| Python Version | Windows | Playwright | Status |
|----------------|---------|------------|--------|
| 3.9            | ✅      | ✅         | OK     |
| 3.10           | ✅      | ✅         | OK     |
| 3.11           | ✅      | ✅         | OK     |
| 3.12           | ✅      | ✅         | OK     |
| 3.13           | ⚠️      | ⚠️         | Parcial |
| 3.14           | ❌      | ❌         | Erro greenlet |

---

## 💡 Dica

Para projetos de produção, **sempre use Python 3.12** (versão mais recente com suporte completo a todas as bibliotecas).

---

## 📞 Suporte

Se continuar enfrentando problemas:

1. Verifique versão do Python: `python --version`
2. Reinstale Playwright: `pip install --force-reinstall playwright`
3. Use Python 3.12: `py -3.12 -m venv venv_312`
4. Consulte issues: https://github.com/microsoft/playwright-python/issues

---

**Desenvolvido e testado com**: Python 3.12.x  
**Data**: 2026-02-04
