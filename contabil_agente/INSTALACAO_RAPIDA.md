# 🚀 GUIA RÁPIDO DE INSTALAÇÃO - ROGIO PRO

## ✅ Instalação em 3 Passos

### 1️⃣ Configurar API Key do GROQ

1. Acesse: <https://console.groq.com/keys>
2. Crie uma conta (se não tiver)
3. Gere uma nova API Key
4. Copie a chave

### 2️⃣ Configurar o Arquivo .env

```powershell
# Navegue até a pasta do projeto
cd "c:\Users\User\Desktop\agent projeto V2\contabil_agente"

# Copie o arquivo de exemplo
Copy-Item .env.example .env

# Edite o arquivo .env e cole sua chave
notepad .env
```

No arquivo `.env`, substitua:

```env
GROQ_API_KEY=sua_chave_groq_aqui
```

Por:

```env
GROQ_API_KEY=gsk_sua_chave_real_aqui
```

### 3️⃣ Iniciar o Servidor

```powershell
# Execute o script de inicialização
.\iniciar_servidor.ps1
```

## 🌐 Acessar a Interface

Abra seu navegador em:

```text
http://localhost:5000/adaptada
```

## 🎯 Pronto

Agora você pode:

- ✅ Conversar com o assistente contábil
- ✅ Trocar entre perfis (Profissional, Rural, Idoso)
- ✅ Gerar documentos em PDF
- ✅ Consultar informações trabalhistas e fiscais

---

## 🔧 Problemas?

### "Erro: GROQ_API_KEY não configurada"

→ Verifique se você editou corretamente o arquivo `.env`

### "Comando não encontrado"

```powershell
# Ative o ambiente virtual manualmente
..\venv\Scripts\Activate.ps1

# Instale as dependências
pip install -r requirements.txt

# Inicie o servidor
python app.py
```

### Porta 5000 já em uso?

Edite o arquivo `.env` e mude a porta:

```env
PORT=5001
```

---

**💡 Dica**: Mantenha o terminal aberto enquanto usa a interface!
