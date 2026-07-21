# 🚀 Como Iniciar o Rogio Pro Chat Interface

## Requisitos

- Python 3.8 ou superior
- Chave API do GROQ ([obtenha aqui](https://console.groq.com/keys))

## Passo 1: Configurar o Ambiente

### 1.1 Criar/Verificar Ambiente Virtual

```powershell
# Se ainda não tiver o ambiente virtual
python -m venv ..\venv

# Ativar o ambiente virtual
..\venv\Scripts\Activate.ps1
```

### 1.2 Instalar Dependências

```powershell
pip install -r requirements.txt
```

## Passo 2: Configurar a API Key

### 2.1 Criar arquivo .env

```powershell
# Copiar o exemplo
Copy-Item .env.example .env
```

### 2.2 Editar o arquivo .env

Abra o arquivo `.env` e adicione sua chave da API do GROQ:

```env
GROQ_API_KEY=gsk_sua_chave_aqui
PORT=5000
FLASK_DEBUG=False
```

**IMPORTANTE:** Obtenha sua chave em [https://console.groq.com/keys](https://console.groq.com/keys)

## Passo 3: Iniciar o Servidor

### Opção 1: Script Automático (Recomendado)

```powershell
.\iniciar_servidor.ps1
```

### Opção 2: Manual

```powershell
# Ativar ambiente virtual
..\venv\Scripts\Activate.ps1

# Iniciar servidor
python app.py
```

## Passo 4: Acessar a Interface

Abra seu navegador em uma das URLs:

- **Interface Adaptável (Todos os Perfis)**: [http://localhost:5000/adaptada](http://localhost:5000/adaptada)
- **Interface Profissional**: [http://localhost:5000/profissional](http://localhost:5000/profissional)
- **Interface Rural**: [http://localhost:5000/rural](http://localhost:5000/rural)
- **Interface Idoso**: [http://localhost:5000/idoso](http://localhost:5000/idoso)

## 🎨 Recursos da Interface Adaptável

A interface `index_adapted.html` possui 3 perfis de usuário:

### 👔 Profissional

- Design moderno e escuro
- Informações técnicas detalhadas
- Ideal para contadores e empresários

### 🌾 Rural

- Interface clara e simples
- Linguagem acessível
- Design limpo com bom contraste

### 👴 Idoso

- Fontes grandes e alto contraste
- Botões maiores e mais espaçados
- Navegação simplificada

## 🔧 Solução de Problemas

### Erro: "GROQ_API_KEY não encontrada"

- Verifique se o arquivo `.env` existe
- Confirme que a chave está corretamente configurada
- Certifique-se de que não há espaços extras

### Erro: "ModuleNotFoundError"

```powershell
pip install -r requirements.txt
```

### Servidor não inicia

```powershell
# Verificar se a porta 5000 está livre
netstat -ano | findstr :5000

# Se estiver em uso, altere a porta no .env
PORT=5001
```

### Interface não carrega

- Verifique se o servidor está rodando
- Confirme a URL correta
- Limpe o cache do navegador (Ctrl+F5)

## 📦 Estrutura de Arquivos

```text
contabil_agente/
├── app.py                  # Servidor Flask principal
├── routes/
│   └── chat.py            # Rotas da API de chat
├── index_adapted.html     # Interface adaptável (PRINCIPAL)
├── .env                   # Configurações (criar)
├── .env.example           # Exemplo de configuração
├── requirements.txt       # Dependências
└── iniciar_servidor.ps1   # Script de inicialização
```

## 🔒 Segurança

- **Nunca** compartilhe sua `GROQ_API_KEY`
- O arquivo `.env` está no `.gitignore` (não é commitado)
- Rate limiting está ativo (20 req/min, 200 req/dia por IP)

## 📞 Suporte

Para problemas ou dúvidas:

1. Verifique os logs do servidor no terminal
2. Consulte a documentação do GROQ
3. Revise os arquivos de configuração

---

### Desenvolvido com ❤️ para Elite Sênior Consultoria
