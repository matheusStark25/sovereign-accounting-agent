# Sovereign Accounting Agent

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/matheusStark25/sovereign-accounting-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/matheusStark25/sovereign-accounting-agent/actions/workflows/ci.yml)

[English](README.md) · **Português**

Assistente de **Departamento Pessoal e contabilidade** para a legislação brasileira: calcula rescisão, férias,
13º, INSS, IRRF, FGTS e folha com aritmética decimal exata, gera o PDF do cálculo, lê e confere 27 tipos de
documento (holerite, TRCT, guias, SPED, XMLs), busca o extrato do FGTS, o extrato do PGMEI e o resumo de NF-e, CT-e e
NFC-e com robôs que **pausam para uma pessoa** resolver login e captcha, e baixa o XML completo da NF-e pelo web service
oficial da SEFAZ com o certificado digital da empresa. Tudo passa por autenticação com verificação em duas etapas,
isolamento entre empresas, defesa contra prompt injection e uma trilha de auditoria à prova de adulteração, ancorada fora do
servidor.

> Os valores calculados vêm do código, nunca de um modelo de linguagem. O LLM só conversa sobre o que não é
> cálculo — e só se a empresa deixar. Se faltar dado ou a tabela de uma competência não existir, o sistema
> **pergunta ou recusa**; ele não estima.

![Maria Helena: demonstrativo de rescisão calculado pelo motor](docs/interface-chat.png)

*Captura da interface real: o demonstrativo da rescisão (valores de exemplo), com cada número vindo do motor de cálculo, o total
com sublinhado duplo, as premissas e as tabelas usadas.*

![Maria Helena conferindo o holerite que a empresa enviou](docs/interface-conferencia.png)

*Também real, com a Groq: a pessoa manda um holerite, a ficha sai com o carimbo da conferência e, perguntada, a Maria Helena
consulta os documentos da empresa e explica a divergência do INSS em reais, com a lei certa. O rodapé diz que ferramenta ela usou.*

<table>
  <tr>
    <td width="50%"><img src="docs/interface-login.png" alt="Tela de entrada: capa de livro-razão e ficha de acesso"></td>
    <td width="50%"><img src="docs/interface-escuro.png" alt="Tema escuro: demonstrativo de férias calculado pelo motor"></td>
  </tr>
  <tr>
    <td><em>Entrada: a capa diz o que o sistema faz; a ficha pede usuário e senha.</em></td>
    <td><em>Tema escuro (segue o do sistema operacional): demonstrativo de férias calculado pelo motor.</em></td>
  </tr>
  <tr>
    <td><img src="docs/interface-painel.png" alt="Painel do escritório: robôs dos portais, aprovações, LGPD e auditoria"></td>
    <td align="center"><img src="docs/interface-celular.png" alt="No celular: demonstrativo do pró-labore" width="62%"></td>
  </tr>
  <tr>
    <td><em>Painel: robôs dos portais (FGTS, PGMEI e notas fiscais), aprovações pendentes, consentimento de IA e verificação da trilha.</em></td>
    <td><em>No celular: "quanto custa um pró-labore de 8 mil?" vira o demonstrativo do motor, com as premissas e as tabelas.</em></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/interface-2fa.png" alt="Verificação em duas etapas: QR code gerado no servidor, chave e confirmação com senha e código" width="62%"></td>
    <td><em>Verificação em duas etapas: o QR code é gerado no servidor (a página não carrega nada de fora). A pessoa confirma com a senha e o código do aplicativo e recebe 10 códigos de recuperação.</em></td>
  </tr>
</table>

*Todas as telas foram capturadas do sistema rodando de verdade (`uvicorn agente_v2.main:app`), com valores e nomes de exemplo.*

## Destaques

- **IA com ferramentas, do jeito seguro:** o modelo escolhe a ferramenta e quem calcula é o código (aritmética decimal,
  tabelas oficiais). CPF e CNPJ viram marcadores antes de ir ao provedor, e há defesa em camadas contra prompt injection:
  triagem, resultado de ferramenta blindado, código-sentinela contra vazamento do prompt e registro na auditoria.
- **Segurança em profundidade:** verificação em duas etapas (TOTP, RFC 6238), JWT com revogação, RBAC e isolamento por
  empresa, trilha HMAC à prova de adulteração com âncora externa, mTLS, Vault e criptografia pós-quântica (ML-KEM-768 +
  X25519, ML-DSA-65).
- **Engenharia de produção:** mais de 1.000 testes automáticos (inclusive de ponta a ponta em navegador real) e um CI com
  lint, testes, pip-audit, bandit, gitleaks, trivy, a pilha completa do docker-compose e a observabilidade conferida de
  ponta a ponta (Prometheus, Alertmanager e Grafana).
- **Domínio real:** regras trabalhistas e fiscais brasileiras, 27 tipos de documento e robôs de portais em que a pessoa
  resolve o captcha (nunca burlado).
- **Servidor MCP:** as mesmas ferramentas saem pelo Model Context Protocol (`python -m agente_v2.cli servidor-mcp`), e o
  Claude Desktop, o Cursor ou qualquer cliente MCP chama o motor de cálculo, com a blindagem e os marcadores do chat.

---

## Sumário

- [Destaques](#destaques)
- [Como funciona](#como-funciona)
- [O que existe de verdade](#o-que-existe-de-verdade)
- [Começando](#começando)
- [API](#api)
- [Servidor MCP](#servidor-mcp)
- [Documentos](#documentos)
- [RPA: FGTS, PGMEI e notas fiscais](#rpa-fgts-pgmei-e-notas-fiscais)
- [Segurança e LGPD](#segurança-e-lgpd)
- [Docker, gateway e Vault](#docker-gateway-e-vault)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Testes](#testes)
- [Licença](#licença)

---

## Como funciona

```mermaid
graph LR
    U[Navegador<br/>agente_v2/web] --> A[API FastAPI<br/>agente_v2.main]
    A --> C[Chat<br/>cálculo determinístico primeiro]
    C -->|só conversa geral<br/>e com consentimento| L[LLM opcional<br/>Groq]
    A --> K[Motor de cálculo<br/>Decimal + tabelas YAML]
    K --> P[PDF com campos<br/>reportlab + AcroForm]
    A --> D[Pipeline de documentos<br/>7 estados]
    D --> W[Worker<br/>DeepSeek opcional]
    D --> R[Revisor<br/>Gemini opcional]
    D --> O[Corretor<br/>regra de evidência]
    O --> N[Detector de anomalias]
    N --> X[Destinos<br/>arquivo, webhook HMAC]
    A -->|fila rpa| Q[Worker Celery do RPA<br/>navegador com a pessoa]
    A -->|fila documentos| B[Worker Celery de lote]
    A --> T[(Auditoria WORM<br/>cadeia HMAC-SHA256)]
    D --> T
    Q --> T
    T -.->|cabeçalho publicado| E[Âncora externa<br/>outro volume ou HTTPS]
```

- **Chat (Maria Helena):** primeiro o `DialogoCalculo` tenta entender o pedido ("calcular rescisão…") e conduz as
  perguntas que faltam; se tudo estiver completo, calcula pelo motor. Pergunta sobre um documento enviado ou sobre a regra
  (prazo, direito, tabela) não vira formulário de cálculo: vai para a Maria Helena, que responde com **ferramentas do
  sistema** em vez de memória: `calcular` (o motor), `tabela_vigente` (faixas, teto e a norma de INSS e IRRF),
  `documentos_recentes` (o que a empresa enviou, com os alertas da conferência), `conciliar_fechamento`,
  `validar_identificadores` e `verificar_conformidade`. Ela nunca soma encargo por conta própria e só cita leis de uma
  lista conferida. CPF, CNPJ, PIS e chave de acesso viram marcadores (`[CPF_1]`) antes de ir ao provedor; a ferramenta
  recebe o valor real só dentro da requisição. Tudo isso só com o consentimento `envio_a_provedor_de_ia`; sem chave de
  LLM o sistema continua funcionando para cálculos e regras. Mensagem que tenta mudar as regras recebe um lembrete do
  sistema, o que as ferramentas devolvem é blindado antes de voltar ao modelo e a resposta que vaza o prompt vira recusa
  (veja [Segurança e LGPD](#segurança-e-lgpd)).
- **Pipeline de documentos:** `RECEIVED → CLASSIFYING → PROCESSING → REVIEWING → CORRECTING → DISPATCHING →
  ARCHIVED`. Worker e Revisor têm modo determinístico (sempre disponível) e usam DeepSeek/Gemini (ou a Groq) quando há
  chave **e** consentimento. O Corretor só aceita um valor sugerido se ele aparecer no texto do documento
  (regra de evidência): o LLM sugere, o documento decide. Documento com instrução escondida para a IA não vai para nenhum
  LLM: é conferido só pelas regras e fica marcado para revisão humana.
- **Auditoria:** cada evento é gravado com PII mascarada numa cadeia HMAC-SHA256 por empresa, com cabeça
  assinada para detectar truncamento. Se a auditoria falhar, a operação falha (a API responde 503). O cabeçalho é
  publicado fora do servidor (âncora externa), o que pega até quem tem a chave e refaz a cadeia.

## O que existe de verdade

| Área | O que está implementado |
|---|---|
| **Cálculo** | Rescisão (sem justa causa, justa causa, pedido de demissão, acordo), férias (com 1/3 e abono pecuniário), 13º, INSS progressivo, IRRF (com a redução da Lei 15.270/2025), FGTS (8%; multa de 40% sem justa causa e 20% em acordo; doméstico 8% + 3,2%), adicionais (horas extras, adicional noturno, insalubridade, periculosidade), folha completa, pró-labore (INSS do sócio, IRRF e custo da empresa), GPS (20%, 11% e 5%), DAS do MEI (INSS + ICMS e/ou ISS) e DARF em atraso (multa e juros da Lei 9.430/1996, com a SELIC acumulada informada, nunca chutada). `Decimal` em tudo; as tabelas ficam em um único arquivo, [`calc/data/tabelas.yaml`](contabil_agente/calc/data/tabelas.yaml). Competência sem tabela → erro explícito. |
| **PDF** | PDF do cálculo com campos AcroForm preenchidos (`/api/v1/calculo/{tipo}/pdf` e no chat). |
| **Documentos** | 27 tipos classificados e extraídos; conferências automáticas em 16 deles (veja [Documentos](#documentos)); detector de anomalias (escore z robusto, duplicidade, competência repetida/futura/antiga); lote assíncrono de até 50 arquivos. |
| **Autenticação** | Login com bcrypt, JWT (expira em 30 min e é revogado no logout), bloqueio da conta após 5 tentativas erradas (15 min), papéis lidos do banco (cabeçalhos de identidade enviados pelo cliente são ignorados), isolamento por empresa (tenant). |
| **Duas etapas (2FA)** | TOTP (RFC 6238, conferido contra os vetores de teste da RFC), opcional por usuário: QR code gerado no servidor, segredo cifrado no banco com AES-256-GCM, código já usado não vale de novo, 10 códigos de recuperação de uso único (guardados como HMAC) e código errado contando como tentativa errada. Ativar e desativar pedem senha e código; o administrador desliga pela CLI para quem perdeu o celular. |
| **Prompt injection** | Defesa em camadas (`security/injecao.py`): triagem em português e inglês (pedido para ignorar as instruções, troca de papel, pedido do prompt, marcadores de chat como `<\|im_start\|>`, texto escondido em caracteres de "tag" do Unicode, que é decodificado e analisado, e controles de direção); resultado de ferramenta blindado antes de voltar ao modelo; código-sentinela por conversa e checagem de vazamento do prompt na resposta; documento com instrução escondida não vai para nenhum LLM e fica para revisão humana. Cada caso vira `security_alert` na auditoria, métrica e alerta. Testado também ao vivo contra o modelo da Groq. |
| **Auditoria** | Trilha WORM por empresa com HMAC-SHA256 encadeado e cabeça assinada, mais a âncora externa (`AUDIT_ANCHOR_DIR` em outro volume e/ou `AUDIT_ANCHOR_URL` em HTTPS): ela acusa até quem tem a chave e refaz a cadeia inteira, ou restaura um backup antigo. |
| **RBAC** | `super_admin`, `tenant_admin`, `accountant`, `auditor`, `viewer`, `guest` com permissões por rota. |
| **LGPD** | Base legal (art. 7) exigida antes de tratar, consentimento por titular e por finalidade, retenção configurável, exclusão de titular respeitando a guarda legal (art. 16), mascaramento de PII em logs e auditoria. |
| **Governança** | Decisões críticas assinadas com ML-DSA-65 (Dilithium); acima do limite do tipo ficam `PENDENTE` até outra pessoa aprovar (regra das duas pessoas); limites em `GOVERNANCA_LIMITES`. |
| **Segredos** | Variáveis de ambiente ou HashiCorp Vault (token ou AppRole). Vault configurado e fora do ar → a API se recusa a subir (sem fallback silencioso). Sem `JWT_SECRET`, `AUDIT_HMAC_KEY` ou `GOVERNANCA_DSA_KEY` ela também não sobe. |
| **Criptografia** | CPF cifrado com ML-KEM-768 + X25519 + AES-GCM (pacote `cryptography`) antes de entrar na fila do Celery; mTLS no gateway (porta 8443) e utilitários mTLS/XML-DSig em `agente_v2/`. |
| **Resiliência** | Circuit breaker, retentativas com backoff exponencial, timeouts, degradação controlada, `/health` e `/ready`. |
| **Agentes** | `TaxAgent` (cálculos), `ValidationAgent` (CPF, CNPJ, PIS, chave de NF-e e documentos), `ReconciliationAgent` (concilia holerites com a guia do FGTS, a GPS e o DARF do IRRF e aponta a diferença em reais), `ComplianceAgent` (regras de conformidade e base legal da LGPD) e `RPAAgent` (extrato do FGTS e do PGMEI, resumo de NF-e, CT-e e NFC-e), orquestrados pela API em `/api/v1/agentes`: uma ação de um agente ou um plano de até 10 passos, com o resultado de um passo alimentando o seguinte. |
| **Voz** | Microfone no navegador → WebSocket `/ws/voz` (áudio em pedaços) → Whisper (`whisper-large-v3-turbo`, via Groq) → chat → resposta frase por frase, lida em voz alta pela voz do navegador (Web Speech API). Exige o consentimento de IA externa (o áudio vai a um terceiro). A Maria Helena adapta o tom (formal, informal ou neutro) ao jeito de quem escreve ou fala e usa as mesmas ferramentas do chat escrito (o MARCOS segue disponível por `AGENTE_PERSONA=MARCOS`). |
| **Observabilidade** | Métricas Prometheus em `/metrics`; log com filtro que mascara CPF, CNPJ, e-mail, telefone e nomes rotulados; e, no perfil `observabilidade` do compose, Prometheus, Alertmanager (8 alertas: API fora do ar, erros 5xx, latência, falha na trilha de auditoria, tentativa de prompt injection, logins recusados, cálculos com erro, voz com falha) e Grafana com o painel "Sovereign Accounting Agent". |
| **Interface web** | Identidade de escritório contábil (papel de livro-razão, selo "MH", demonstrativo com pontilhado e total com sublinhado duplo, carimbo de conferência nos documentos, tema escuro). Login, conversa com atalhos, envio de documento, microfone e leitura das respostas em voz alta, painel (robôs do FGTS, do PGMEI e das notas fiscais, com uma ou várias chaves e o resumo de cada nota na tela; aprovações pendentes, consentimento de IA, verificação da trilha e das âncoras, verificação em duas etapas com QR code). Funciona no celular. |
| **CLI** | `python -m agente_v2.cli` cria usuários, desliga a verificação em duas etapas de quem perdeu o celular (`desativar-2fa`), gera segredos, chaves do RPA e do ML-DSA, verifica a auditoria, publica e confere as âncoras externas (`ancorar-auditoria`, `conferir-ancoras`), confere de verdade as chaves e modelos de IA (`verificar-ia`), grava a calibragem de portais (`calibrar-fgts`) e baixa extratos do FGTS e do PGMEI e consulta NF-e, CT-e e NFC-e, com a pessoa resolvendo só o captcha (`baixar-extrato`), envia sozinho ao sistema o PDF que você baixou no navegador normal (`observar-pasta`), baixa o XML da NF-e com o certificado A1 (`baixar-xml-nfe`) e serve as ferramentas para clientes MCP (`servidor-mcp`, veja [Servidor MCP](#servidor-mcp)). |

## Começando

Requisitos: Python 3.12. Redis só é necessário para as filas (lote de documentos e RPA).

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # versões exatas testadas: requirements.lock
```

Gere os segredos e preencha o `.env` (copie de `.env.example`):

```bash
cp .env.example .env
python -m agente_v2.cli gerar-segredo              # cole em JWT_SECRET
python -m agente_v2.cli gerar-segredo              # cole em AUDIT_HMAC_KEY
python -m agente_v2.cli gerar-segredo              # cole em REDIS_PASSWORD
python -m agente_v2.cli gerar-chave-governanca     # cole a linha GOVERNANCA_DSA_KEY=... inteira
```

Defina `ADMIN_USERNAME` e `ADMIN_PASSWORD` (cria um `super_admin` no primeiro acesso, se ainda não houver
usuários; apague `ADMIN_PASSWORD` depois) e suba a API:

```bash
uvicorn agente_v2.main:app --env-file .env --host 127.0.0.1 --port 8000
```

Abra <http://127.0.0.1:8000> e entre. Para criar outros usuários:

```bash
python -m agente_v2.cli criar-usuario --usuario maria --tenant empresa_a --papeis accountant
```

Para desenvolvimento local use `AGENTE_ENV=dev`: se faltarem, a API cria um `JWT_SECRET` temporário e guarda uma
chave de auditoria e uma chave de governança em `DATA_DIR`, e liga a documentação em `/docs`. Em produção (o
padrão) ela recusa subir sem os segredos obrigatórios. As chaves de IA são opcionais: `GROQ_API_KEY` (conversa),
`DEEPSEEK_API_KEY` (Worker) e `GEMINI_API_KEY` (Revisor); sem as duas últimas, a Groq faz esses papéis. Os provedores
renomeiam e desligam modelos, então `python -m agente_v2.cli verificar-ia --env-file .env` confere chave, modelo e
uma chamada real. Os dados ficam em `DATA_DIR` (padrão `contabil_agente/data`).

## API

A documentação interativa (`/docs`) só fica ligada com `AGENTE_ENV=dev`. Rotas principais, todas com JWT
(`POST /token`) exceto `/health`, `/ready` e `/metrics`:

| Rota | Para quê |
|---|---|
| `POST /token`, `POST /logout`, `GET /users/me`, `POST /users` | Login (com `codigo_2fa` quando a conta tem duas etapas: sem ele a resposta é 401 com `X-MFA-Required: totp`), logout, usuário atual, criar usuário (admin) |
| `GET /users/me/2fa`, `POST /users/me/2fa/iniciar`, `POST /users/me/2fa/ativar`, `POST /users/me/2fa/desativar` | Verificação em duas etapas: estado, QR code, ativar com senha e código (devolve os códigos de recuperação uma vez só) e desativar |
| `POST /api/chat`, `GET /api/chat/{sessao}`, `GET /api/chat/{sessao}/pdf` | Conversa, histórico e PDF do último cálculo |
| `GET /api/v1/calculo/tipos`, `POST /api/v1/calculo/{tipo}`, `POST /api/v1/calculo/{tipo}/pdf` | Cálculo direto: `rescisao`, `ferias`, `decimo_terceiro`, `inss`, `irrf`, `fgts`, `folha`, `prolabore`, `gps`, `das_mei`, `darf` |
| `GET /api/v1/documentos/tipos`, `POST /api/v1/documentos`, `POST /api/v1/documentos/lote` | Tipos aceitos, processar um arquivo, processar até 50 em segundo plano (202) |
| `POST /api/v1/rpa/fgts`, `POST /api/v1/rpa/pgmei`, `POST /api/v1/rpa/nfe`, `GET /api/v1/rpa/jobs/{id}` | Pedir o extrato do FGTS (CPF), do PGMEI (CNPJ) ou o resumo de uma NF-e, CT-e ou NFC-e (chave de 44 dígitos) (202) e acompanhar o trabalho |
| `POST /api/v1/rpa/nfe/lote` | Até 20 chaves de uma vez: um trabalho por chave (se uma for inválida, nenhuma entra na fila) |
| `GET /api/v1/agentes`, `POST /api/v1/agentes/{agente}/{acao}`, `POST /api/v1/agentes/orquestrar` | Catálogo dos agentes, uma ação de um agente, ou um plano com vários passos |
| `WS /ws/voz` | Canal de voz: o 1º quadro autentica (`{"tipo": "autenticar", "token": ...}`), depois `inicio`, áudio em pedaços e `fim` (ou `texto`); volta `transcricao`, `fala` frase por frase e `fim_resposta` |
| `POST /api/v1/governanca/decisoes`, `GET …/pendentes`, `GET …/decisoes/{id}`, `POST …/aprovar`, `POST …/rejeitar` | Decisões críticas assinadas e aprovação por limite |
| `GET /api/v1/lgpd/finalidades`, `POST/GET /api/v1/lgpd/consentimentos`, `DELETE /api/v1/lgpd/titular`, `GET /api/v1/lgpd/retencao`, `POST /api/v1/lgpd/retencao/executar` | Consentimento, exclusão de titular e retenção |
| `GET /api/v1/auditoria/verificar`, `POST /api/v1/auditoria/ancorar` | Confere a cadeia HMAC da sua empresa e as âncoras externas; publica a âncora agora |
| `GET /health`, `GET /ready`, `GET /metrics` | Saúde, prontidão (espaço em disco e Vault, quando configurado) e métricas Prometheus |

Exemplo (cálculo direto):

```bash
TOKEN=$(curl -s -d "username=maria&password=..." http://127.0.0.1:8000/token | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"salario":3000,"tipo_rescisao":"sem justa causa","data_admissao":"10/03/2023","data_demissao":"15/09/2026","aviso_previo":"indenizado","saldo_fgts":12000}' \
  http://127.0.0.1:8000/api/v1/calculo/rescisao
```

Nesse cenário a resposta traz `total_proventos` 10566.67, `total_descontos` 313.19, `total_liquido` 10253.48,
multa de FGTS 5052.8 (40% sobre saldo + depósito rescisório) e depósito rescisório 632.0.

## Servidor MCP

As ferramentas do chat também ficam disponíveis para qualquer assistente que fale o
[Model Context Protocol](https://modelcontextprotocol.io) (Claude Desktop, Claude Code, Cursor e outros). O modelo escolhe
a ferramenta e preenche os argumentos; quem faz o trabalho é o código do sistema:

| Ferramenta | O que faz |
|---|---|
| `calcular` | Rescisão, férias, 13º, INSS, IRRF, FGTS, folha, pró-labore, GPS, DAS do MEI e DARF em atraso, com as tabelas oficiais |
| `tabela_vigente` | A tabela de INSS ou IRRF vigente numa competência, com a norma |
| `validar_identificadores` | Dígito verificador de CPF, CNPJ, PIS e chave de acesso de 44 dígitos |
| `conciliar_fechamento` | Holerites contra a guia do FGTS, a GPS e o DARF do IRRF, com a diferença em reais |
| `verificar_conformidade` | Um pagamento conferido contra as regras de conformidade (salário mínimo, CPF, competência…) |

```bash
python -m agente_v2.cli servidor-mcp
```

Roda na máquina, por stdio (JSON-RPC 2.0, versões 2024-11-05 a 2025-06-18 do protocolo), e não precisa de SDK: a imagem
Docker e as dependências auditadas continuam as mesmas. No Claude Desktop, entra no `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sovereign": {
      "command": "python",
      "args": ["-m", "agente_v2.cli", "servidor-mcp"],
      "env": {"PYTHONPATH": "/caminho/para/sovereign-accounting-agent"}
    }
  }
}
```

As proteções do chat valem aqui também: todo resultado de ferramenta passa pela blindagem contra prompt injection, CPF,
CNPJ, PIS e chave de acesso voltam como marcadores (`[CPF_1]`) e nada fica gravado (sem banco, sem histórico).
`documentos_recentes` fica de fora porque depende do histórico de documentos de uma empresa, que fica atrás do login da
API. Os testes (`contabil_agente/tests/test_mcp_servidor.py`) cobrem o protocolo, essas proteções e o processo de verdade
por stdio.

## Documentos

Classificação por assinaturas ponderadas (empate entre tipos reduz a confiança; se nenhum tipo atinge a
pontuação mínima o resultado diz que não identificou o tipo, em vez de chutar) e extração por tipo. Aceita PDF,
XML, TXT e CSV de até 25 MB. Os extratores só retêm CPF e CNPJ cujo dígito verificador é válido.

| Categoria | Tipos | O que é conferido além da extração |
|---|---|---|
| Trabalhista | Holerite, TRCT, contrato de trabalho | Holerite: proventos − descontos = líquido e recálculo de INSS, IRRF (sem dependentes) e FGTS pelo motor. TRCT: verbas × total bruto, bruto − descontos = líquido, datas invertidas. Contrato: salário abaixo do mínimo da admissão, jornada acima de 44 h. |
| Trabalhista (só extração) | Recibo de férias, ASO, CAGED, RAIS | — |
| Federal | DARF, DIRF, informe de rendimentos | DARF: principal + multa + juros = total. Informe: IRRF maior que o rendimento, CPF inválido. DIRF: avisa que foi extinta. |
| Federal (só extração) | DAS, DCTF, DCTFWeb, PER/DCOMP | — |
| Previdenciário e FGTS | GPS, GRRF, guia do FGTS Digital, extrato do FGTS | GPS: soma dos componentes. GRRF/guia: 8% da base × valor da guia. Extrato: dígito verificador do PIS. |
| Previdenciário (só extração) | GFIP/SEFIP | — |
| SPED | ECD, ECF, EFD ICMS/IPI, EFD Contribuições | Estrutura dos registros, CNPJ do 0000, período invertido. |
| XML | NF-e, eventos do eSocial | NF-e: dígito da chave de acesso, CNPJ e número dentro da chave, vNF = soma dos totais. eSocial: evento reconhecido, CPF e CNPJ válidos. |
| XML / municipal (só extração) | EFD-Reinf, NFS-e | — |

O detector de anomalias (histórico em SQLite, separado por empresa) marca: arquivo já processado, competência
repetida, competência no futuro ou com mais de 5 anos, valor zerado, valor atípico (só com 5+ observações
anteriores), INSS acima de 14% e IRRF acima de 27,5% dos proventos. Isso vira alerta no resultado e na
auditoria; alerta de erro, arquivo duplicado ou valor atípico marcam `requer_revisao`.

**Destinos do resultado:** o arquivo (documento original + JSON em
`DATA_DIR/arquivo/<empresa>/<tipo>/<sha256>`, permissão `0600`) está sempre ligado. Defina
`DOCUMENTOS_WEBHOOK_URL` e `DOCUMENTOS_WEBHOOK_SECRET` para também enviar cada resultado por POST assinado
(`X-Signature: sha256=<HMAC-SHA256 do corpo>`, HTTPS obrigatório, com retentativas e disjuntor); ele recebe o
resultado de **todas** as empresas da instalação, então aponte só para um serviço seu. Uma falha do webhook
vira alerta e não impede o arquivamento. Também existe `CallbackDestino` (uma função Python), disponível só
pela API Python ao montar o `DocumentDispatcher`.

## RPA: FGTS, PGMEI e notas fiscais

Robôs (Playwright) com o mesmo princípio: **a pessoa só resolve o captcha (ou o login); o resto é do robô**, e o
robô não trava por bobeira.

- **FGTS** (extrato por CPF) e **PGMEI** (extrato/DAS do MEI por CNPJ, portal público da Receita). O PDF baixado
  entra no pipeline de documentos.
- **Notas fiscais** pela chave de 44 dígitos; o modelo gravado na chave escolhe o portal: **NF-e** (portal nacional),
  **CT-e** (portal nacional do CT-e) e **NFC-e** (SEFAZ-SP por padrão; outra UF por `NFCE_PORTAL_CONFIG`). A pessoa clica
  no hCaptcha (NF-e e CT-e) ou digita o código da imagem (NFC-e de SP); o robô lê a tela da nota (número, série, emissão,
  valor, situação, emitente, destinatário, tomador) por rótulos e grava `consulta_<modelo>_<sha>.json`. CPF de pessoa
  física sai mascarado. Várias chaves de uma vez: pela API (`/api/v1/rpa/nfe/lote`), pelo painel (uma por linha) ou
  repetindo `--documento` na CLI.
- Só baixa PDF de verdade (confere a assinatura e o tamanho), calcula o SHA-256 e guarda `0600`. Captcha que vence
  (ou código digitado errado) volta para a pessoa resolver de novo (até `tentativas_captcha`).
- Só navega nos hosts permitidos, conferidos de novo depois de cada redirecionamento.
- O CPF/CNPJ nunca vai em claro para o broker (cifrado com ML-KEM + X25519 + AES-GCM) e na auditoria só entra o hash.
- Sem captcha solver e sem flags para esconder a automação (um teste confere que não existem no código).

**Quando o site muda ou demora** (para não travar por bobeira):

1. **Espera** o elemento aparecer (`espera_elemento_s`, 15 s): páginas lentas ou que montam a tela por JavaScript.
2. Procura em **todos os quadros** da página, inclusive `iframe`.
3. Se o seletor configurado não acha nada, acha **pelo que o elemento é**: rótulo, placeholder, nome/id, texto do
   botão ou do link (`rotulo_campo`, `rotulo_envio`, `rotulo_download`). Anota na trilha o passo `seletor_alternativo`
   com o seletor que você deve pôr na configuração.
4. Se ainda assim não achar, **pede ajuda na própria janela** em vez de abortar: aparece um aviso amarelo com o botão
   "Terminei esta etapa". A pessoa faz o passo (ou clica no link do PDF, que o robô pega) e o robô continua dali
   (`ajuda_humana`, ligado por padrão). Em todos os casos ele salva um `diagnostico_<etapa>_<hora>.json` com a
   estrutura da página (botões, campos, links; números e e-mails mascarados), sem nada digitado.
5. Se o portal **reprova o navegador automatizado** (ex.: "Comportamento de Robô"), ele falha na hora, com
   mensagem clara e **sem nova tentativa** (insistir só piora): baixe o PDF no seu navegador normal. Com o
   `observar-pasta` ligado ele entra sozinho no sistema (veja abaixo); no painel, o botão "Enviar o PDF que baixei" faz o
   mesmo na hora.

Como rodar, direto da linha de comando (abre a janela; você resolve o captcha e só):

```bash
python -m agente_v2.cli baixar-extrato --portal pgmei --documento 11.222.333/0001-81 --ano 2026 --canal msedge
python -m agente_v2.cli baixar-extrato --portal fgts  --documento 529.982.247-25 --canal msedge
python -m agente_v2.cli baixar-extrato --portal nfe   --documento <chave 1> --documento <chave 2> --canal msedge
```

Ou pela API (fila `rpa`, com a pessoa na máquina do worker):

```bash
python -m agente_v2.cli gerar-chaves-rpa --saida ./chaves   # coloque RPA_PQC_PUBLIC_KEY na API e RPA_PQC_PRIVATE_KEY no worker
playwright install chromium                                  # ou use FGTS_BROWSER_CHANNEL=msedge|chrome
celery -A contabil_agente.tarefas worker -Q rpa --pool=solo --loglevel=info
```

O worker `rpa` precisa rodar **em uma máquina com tela** (a pessoa resolve o captcha na janela) e enxergar o
mesmo `DATA_DIR` e os mesmos segredos da API (status das tarefas, auditoria e LGPD ficam em arquivos ali). O
caminho mais simples é rodar API e worker no mesmo computador. Ele **não** está no `docker-compose.yml`, de
propósito. Configuração: `FGTS_CAIXA_URL`, `FGTS_PORTAL_CONFIG`, `FGTS_BROWSER_CHANNEL`, `FGTS_BROWSER_USER_DATA_DIR`
(e `PGMEI_PORTAL_CONFIG`, `PGMEI_BROWSER_CHANNEL`, `PGMEI_BROWSER_USER_DATA_DIR`; e os mesmos três com os prefixos `NFE_`, `CTE_` e `NFCE_`); o YAML aceita seletores,
rótulos, tempos, `ajuda_humana` e `capturar_tela_na_falha` (a captura de tela pode mostrar dados pessoais, por
isso vem desligada).

**Nos portais reais (testado em 2026-10-17):** o PGMEI e a Caixa recusam navegador controlado por automação (o PGMEI
responde "13896 - Impedido por proteção Captcha. Comportamento de Robô"). Nesse caso o robô avisa, e você baixa o PDF no
navegador normal e envia por `POST /api/v1/documentos` (ou deixa o `observar-pasta` enviar), que classifica, extrai,
confere e arquiva. Nas consultas de NF-e, CT-e e NFC-e de SP (conferidas em 2026-10-19), o robô acha nas telas reais o
campo da chave, o botão e o captcha (caixa de seleção do hCaptcha na NF-e e no CT-e, código de imagem na NFC-e). Os robôs
foram testados de ponta a ponta contra portais falsos com a mesma estrutura, que reproduzem mudança de layout, demora,
`iframe`, captcha vencido, código errado e bloqueio.

### PDF baixado no navegador normal entra sozinho (`observar-pasta`)

```bash
python -m agente_v2.cli observar-pasta --usuario maria        # olha a pasta Downloads; a senha vem de AGENTE_SENHA ou é perguntada
```

Você baixa o extrato do FGTS ou o DAS no seu navegador de sempre e o observador envia cada PDF novo a
`POST /api/v1/documentos` assim que ele termina de ser gravado. Só PDF de verdade (até 25 MB); o mesmo conteúdo nunca
vai duas vezes (SHA-256 guardado na pasta); falha de rede tenta de novo, recusa da API não. Ele não toca no navegador nem
no portal.

### XML completo da NF-e pelo certificado digital (`baixar-xml-nfe`)

```bash
python -m agente_v2.cli baixar-xml-nfe --pfx empresa.pfx --uf SP --chave <chave> --usuario maria   # senha do .pfx em CERTIFICADO_SENHA
```

Usa o web service oficial **NFeDistribuicaoDFe** do Ambiente Nacional (sem navegador e sem captcha), com o certificado
A1 da empresa na conexão (mTLS). O CNPJ sai do próprio certificado (campo da ICP-Brasil). Grava `nfe_<chave>.xml` e, com
`--usuario`, já envia ao pipeline, que o lê como `NFE_XML` e confere chave, CNPJ, número e total. A SEFAZ só entrega notas
em que a empresa aparece; quando ela manda só o resumo, o comando diz para registrar a "Ciência da Operação" e consultar
de novo; consumo indevido (656) e nota inexistente (137) também vêm com o motivo. A chave privada do certificado nunca vai
em claro para o disco. Os endereços de produção e homologação foram conferidos em 2026-10-19 (TLS válido, 403 sem
certificado); o fluxo completo foi testado com mTLS de verdade contra uma SEFAZ falsa com o formato do `retDistDFeInt`.

## Segurança e LGPD

- **Tenant isolado:** cada consulta carrega o `tenant_id` do token; acessar dado de outra empresa dá 404/403
  (testado contra IDOR).
- **Verificação em duas etapas:** no painel, "Ativar" mostra o QR code (gerado no servidor, a página não carrega nada de
  fora); a pessoa confirma com a senha e o código do aplicativo e recebe 10 códigos de recuperação. Daí em diante o login
  pede o código. `MFA_ENCRYPTION_KEY` dá uma chave própria para o segredo no banco (sem ela, é derivada do `JWT_SECRET`
  por HKDF).
- **Prompt injection:** a mensagem que tenta mudar as regras ou obter o prompt recebe um lembrete do sistema; o que as
  ferramentas devolvem passa por `blindar` (texto invisível sai, trecho suspeito vira aviso); a resposta que repete as
  regras ou o código-sentinela da conversa é trocada por uma recusa; e documento com instrução escondida segue só pelas
  regras, sem IA, com o alerta `instrucao_para_ia`. A trilha guarda a origem e os motivos de cada caso, nunca o texto.
- **Sem segredo no código:** um teste varre os arquivos versionados atrás de chaves e dados de execução, e o CI passa o
  `gitleaks` nos arquivos e nos commits novos.
- **Varreduras no CI:** `pip-audit` (dependências), `bandit` (código), `gitleaks` (segredos) e `trivy` (vulnerabilidades
  da imagem Docker, HIGH e CRITICAL com correção disponível). Cada achado vira anotação na execução.
- **Cabeçalhos:** CSP restritiva, `X-Content-Type-Options`, `Referrer-Policy`, CORS por lista (`ALLOWED_ORIGINS`),
  HSTS com `HTTPS_ONLY=1`, limite de tamanho do corpo JSON.
- **Gateway:** nginx com TLS (443) e mTLS obrigatório na 8443 (`ssl_verify_client on`); identidade enviada pelo
  cliente nunca é repassada; `/metrics` não é exposto na porta pública.
- **Auditoria verificável e ancorada:** `python -m agente_v2.cli verificar-auditoria` ou `GET /api/v1/auditoria/verificar`
  conferem a cadeia. `python -m agente_v2.cli ancorar-auditoria` (agende de hora em hora) publica o cabeçalho de cada
  trilha em `AUDIT_ANCHOR_DIR` (pasta em outro volume) e/ou `AUDIT_ANCHOR_URL` (serviço HTTPS); `conferir-ancoras` e a
  rota de verificação acusam a cadeia refeita com a chave e o backup antigo restaurado, que a cadeia sozinha não pega.
- **LGPD:** finalidades e bases legais em `contabil_agente/lgpd/`; retenção em `RETENCAO_CONFIG`; exclusão de
  titular preserva o que a lei manda guardar.

## Docker, gateway e Vault

```bash
cp .env.example .env                                  # preencha os segredos: o compose se recusa a subir sem eles
docker compose up --build                             # API (8000), worker de documentos e Redis com senha
docker compose --profile gateway up --build           # + nginx: https://localhost e mTLS em :8443 (certificados em ./certs)
docker compose --profile dev up --build               # + Vault em modo dev (nunca em produção)
docker compose --profile observabilidade up -d        # + Prometheus (9090), Alertmanager (9093) e Grafana (3000), só em 127.0.0.1
```

Para o perfil `observabilidade`, defina `GRAFANA_ADMIN_PASSWORD` no `.env` (o Grafana se recusa a subir sem ela) e, se quiser receber os alertas fora da tela do Alertmanager, `ALERTA_WEBHOOK_URL` (só HTTPS).

Para gerar certificados de desenvolvimento (CA própria, servidor e cliente, válidos por 7 dias):
`python -c "from agente_v2.mtls import emitir_certificados_dev as e; e('certs')"`. Em produção use certificados
da sua autoridade. Há também uma unidade systemd
de exemplo em `deploy/maria-helena.service`.

## Estrutura do projeto

```
agente_v2/                  API e infraestrutura de execução
├── main.py                 aplicação FastAPI (create_app) e rotas
├── auth.py, config.py      autenticação (reexport) e configuração por ambiente
├── vault_client.py         Vault (token/AppRole) e carga de segredos
├── mtls.py, signing.py     certificados mTLS e assinatura XML-DSig
├── rotas_agentes.py        API dos agentes e do orquestrador
├── rotas_voz.py            canal de voz (WebSocket)
├── observador.py           pasta observada: PDF baixado no navegador normal entra no sistema
├── cli.py, logging_setup.py
├── web/                    interface (index.html, app.css, app.js)
└── tests/                  API, Vault, mTLS, assinatura e front-end (navegador real)

contabil_agente/            domínio e serviços
├── calc/                   motor de cálculo (Decimal) e tabelas YAML
├── chat/                   motor da conversa, LLM com ferramentas, marcadores de dados pessoais, armazenamento, servidor MCP
├── intelligence/           diálogo de cálculo, extração, auditoria forense, FSM
├── documentos/             leitura, 27 tipos, validadores, PDF
├── pipeline/               dispatcher, agentes, anomalias, evidência, destinos
├── agentes/                TaxAgent, ValidationAgent, ReconciliationAgent, ComplianceAgent, RPAAgent e o orquestrador
├── voz/                    Whisper (fala para texto)
├── rpa/                    robôs do FGTS, do PGMEI e das notas fiscais (NF-e, CT-e, NFC-e), pausa humana, calibragem
├── sefaz/                  web service oficial NFeDistribuicaoDFe (XML da NF-e com certificado A1)
├── tarefas/                Celery (filas documentos e rpa)
├── security/               auth, duas etapas (TOTP), RBAC, auditoria WORM e âncora externa, prompt injection, PQC, Vault
├── lgpd/                   base legal, consentimento, retenção, anonimização
├── middleware/             autenticação, cabeçalhos, limite de uso, métricas
├── resilience/             circuit breaker, retry, timeouts, readiness
├── governance/ governance_manager.py   decisões assinadas e aprovação
├── core/, config/, tools/, models/, utils/, orchestrator/
└── tests/                  testes de cálculo, pipeline, RPA, LGPD, infraestrutura…

rules/compliance_rules.yaml regras de conformidade
observabilidade/           Prometheus, alertas, Alertmanager e painel do Grafana
Dockerfile, docker-compose.yml, nginx/, deploy/, .github/workflows/ci.yml
```

## Testes

```bash
pip install -r requirements-dev.txt
playwright install chromium            # os testes do RPA e do front-end usam um navegador de verdade
pytest
flake8 agente_v2 contabil_agente --select=E9,F63,F7,F82,F401,F811,F841,F541
```

A suíte (mais de 1.000 testes) cobre o motor de cálculo (inclusive cenários conferidos à mão), a API e o isolamento entre
empresas, o robô contra um portal falso local, o front-end em navegador real, a cadeia de auditoria (adulteração,
truncamento e, com a âncora, cadeia refeita com a chave e backup restaurado), a verificação em duas etapas (vetores das
RFCs 4226 e 6238), os ataques de prompt injection conhecidos (e os textos normais que não podem virar alarme falso), o
servidor MCP (protocolo, blindagem, marcadores e o processo de verdade por stdio), LGPD, governança, criptografia e a
consistência da infraestrutura. A criptografia pós-quântica
(ML-KEM-768 e ML-DSA-65, do pacote `cryptography`) é conferida a cada execução contra duas implementações
independentes (`kyber-py` e `dilithium-py`, só nos testes). Os testes de IA ao vivo
(`contabil_agente/tests/test_ia_ao_vivo.py`) rodam quando há chave em `.env.teste` (verificados com a Groq, inclusive
a tentativa de prompt injection contra o modelo de verdade). O CI (`.github/workflows/ci.yml`) roda lint, testes,
`pip-audit`, `bandit`, `gitleaks`, a construção da imagem com o `trivy` e a **pilha completa** do `docker-compose.yml` (API, worker, Redis com senha
e nginx): confere o `/health` pelo TLS, o `/metrics` fechado na porta pública, a porta 8443 recusando quem não
tem certificado de cliente (mTLS), o login com uma rota protegida e o worker falando com o Redis. Outro job sobe a observabilidade: o Prometheus enxerga a API e carrega as 8 regras sem erro, uma métrica real aparece depois de usar a API, o Grafana abre com o painel e a fonte de dados (e exige login), e um alerta de verdade (derrubar a API) chega ao Alertmanager.

## Licença

[MIT](LICENSE)
