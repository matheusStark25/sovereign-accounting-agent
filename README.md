# Sovereign Accounting Agent

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Assistente de **Departamento Pessoal e contabilidade** para a legislação brasileira: calcula rescisão, férias,
13º, INSS, IRRF, FGTS e folha com aritmética decimal exata, gera o PDF do cálculo, lê e confere 27 tipos de
documento (holerite, TRCT, guias, SPED, XMLs) e busca o extrato do FGTS com um robô que **pausa para uma
pessoa** resolver login e captcha. Tudo passa por autenticação, isolamento entre empresas e uma trilha de
auditoria à prova de adulteração.

> Os valores calculados vêm do código, nunca de um modelo de linguagem. O LLM só conversa sobre o que não é
> cálculo — e só se a empresa deixar. Se faltar dado ou a tabela de uma competência não existir, o sistema
> **pergunta ou recusa**; ele não estima.

---

## Sumário

- [Como funciona](#como-funciona)
- [O que existe de verdade](#o-que-existe-de-verdade)
- [Limites conhecidos (leia antes de usar)](#limites-conhecidos-leia-antes-de-usar)
- [Começando](#começando)
- [API](#api)
- [Documentos](#documentos)
- [RPA do FGTS](#rpa-do-fgts)
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
```

- **Chat:** primeiro o `DialogoCalculo` tenta entender o pedido ("calcular rescisão…") e conduz as perguntas
  que faltam; se tudo estiver completo, calcula pelo motor. Só o que sobra vai ao LLM, com CPF/CNPJ/e-mail
  mascarados e apenas se a empresa registrou o consentimento `envio_a_provedor_de_ia`. Sem chave de LLM o
  sistema continua funcionando para cálculos e regras.
- **Pipeline de documentos:** `RECEIVED → CLASSIFYING → PROCESSING → REVIEWING → CORRECTING → DISPATCHING →
  ARCHIVED`. Worker e Revisor têm modo determinístico (sempre disponível) e usam DeepSeek/Gemini quando há
  chave **e** consentimento. O Corretor só aceita um valor sugerido se ele aparecer no texto do documento
  (regra de evidência): o LLM sugere, o documento decide.
- **Auditoria:** cada evento é gravado com PII mascarada numa cadeia HMAC-SHA256 por empresa, com cabeça
  assinada para detectar truncamento. Se a auditoria falhar, a operação falha (a API responde 503).

## O que existe de verdade

| Área | O que está implementado |
|---|---|
| **Cálculo** | Rescisão (sem justa causa, justa causa, pedido de demissão, acordo), férias (com 1/3 e abono pecuniário), 13º, INSS progressivo, IRRF (com a redução da Lei 15.270/2025), FGTS (8%; multa de 40% sem justa causa e 20% em acordo; doméstico 8% + 3,2%), adicionais (horas extras, adicional noturno, insalubridade, periculosidade) e folha completa. `Decimal` em tudo; as tabelas ficam em um único arquivo, [`calc/data/tabelas.yaml`](contabil_agente/calc/data/tabelas.yaml). Competência sem tabela → erro explícito. |
| **PDF** | PDF do cálculo com campos AcroForm preenchidos (`/api/v1/calculo/{tipo}/pdf` e no chat). |
| **Documentos** | 27 tipos classificados e extraídos; conferências automáticas em 16 deles (veja [Documentos](#documentos)); detector de anomalias (escore z robusto, duplicidade, competência repetida/futura/antiga); lote assíncrono de até 50 arquivos. |
| **Autenticação** | Login com bcrypt, JWT, bloqueio da conta após 5 senhas erradas (15 min), papéis lidos do banco (cabeçalhos de identidade enviados pelo cliente são ignorados), isolamento por empresa (tenant). |
| **RBAC** | `super_admin`, `tenant_admin`, `accountant`, `auditor`, `viewer`, `guest` com permissões por rota. |
| **LGPD** | Base legal (art. 7) exigida antes de tratar, consentimento por titular e por finalidade, retenção configurável, exclusão de titular respeitando a guarda legal (art. 16), mascaramento de PII em logs e auditoria. |
| **Governança** | Decisões críticas assinadas com ML-DSA-65 (Dilithium); acima do limite do tipo ficam `PENDENTE` até outra pessoa aprovar (regra das duas pessoas); limites em `GOVERNANCA_LIMITES`. |
| **Segredos** | Variáveis de ambiente ou HashiCorp Vault (token ou AppRole). Vault configurado e fora do ar → a API se recusa a subir (sem fallback silencioso). Sem `JWT_SECRET`, `AUDIT_HMAC_KEY` ou `GOVERNANCA_DSA_KEY` ela também não sobe. |
| **Criptografia** | CPF cifrado com ML-KEM-768 + X25519 + AES-GCM antes de entrar na fila do Celery; mTLS no gateway (porta 8443) e utilitários mTLS/XML-DSig em `agente_v2/`. |
| **Resiliência** | Circuit breaker, retentativas com backoff exponencial, timeouts, degradação controlada, `/health` e `/ready`. |
| **Observabilidade** | Métricas Prometheus em `/metrics`, log com filtro que mascara CPF, CNPJ, e-mail, telefone e nomes rotulados. |
| **Interface web** | Login, conversa com atalhos, envio de documento, painel (extrato do FGTS, aprovações pendentes, consentimento de IA, verificação da trilha). Funciona no celular. |
| **CLI** | `python -m agente_v2.cli` cria usuários, gera segredos, chaves do RPA e do Dilithium, e verifica a auditoria. |

## Limites conhecidos (leia antes de usar)

Estas são as coisas que o código **não** garante, ditas de frente:

- **Robô do FGTS.** Os seletores padrão do portal da Caixa são palpites genéricos: o extrato exige login e o
  site muda. Foi testado contra um portal falso local (login, captcha, redirecionamento, download), **não contra
  o portal real**. Valide e ajuste os seletores em `FGTS_PORTAL_CONFIG` antes de depender dele.
- **Captcha.** O robô nunca tenta resolver captcha nem disfarçar a automação. Ele para e espera uma pessoa na
  janela do navegador.
- **Docker.** `Dockerfile`, `docker-compose.yml` e `nginx/` têm testes de consistência (arquivos referenciados
  existem, segredos obrigatórios, usuário não-root, mTLS exigido) e o CI constrói a imagem e testa o `/health`,
  mas eu não pude subir os contêineres na máquina de desenvolvimento.
- **Criptografia pós-quântica.** ML-KEM e ML-DSA vêm de implementações em Python puro (`kyber-py`,
  `dilithium-py`), sem auditoria independente nem garantia de tempo constante. Servem para o que está descrito
  acima; não as trate como biblioteca criptográfica auditada.
- **LLMs.** Os adaptadores de DeepSeek, Gemini e Groq foram testados com respostas simuladas, não com as
  contas reais. O GitHub Copilot não tem API para ser chamado de dentro de um sistema, então o Corretor não o
  usa: ele aplica regras de evidência sobre as sugestões do Worker e do Revisor.
- **Sem OCR.** PDF escaneado (sem camada de texto) é sinalizado e não é lido; nada é inventado no lugar. Limites:
  25 MB e 300 páginas por arquivo.
- **LGPD.** O projeto implementa os mecanismos (base legal, consentimento, retenção, exclusão, mascaramento).
  Estar em conformidade é uma condição jurídica e organizacional da empresa que o opera; nenhuma ferramenta
  entrega isso sozinha.
- **Nem todo documento tem conferência.** 11 dos 27 tipos só são classificados e extraídos, sem conferência
  cruzada: DAS, GFIP, DCTF, DCTFWeb, PER/DCOMP, CAGED, RAIS, NFS-e, EFD-Reinf, recibo de férias e ASO.
- **Limite de uso em memória.** O limitador de login/chat é por processo; com vários processos use também o
  gateway (o `nginx.conf` já limita `/token` e o tráfego geral).
- **SQLite.** Chat, LGPD, status de tarefas e histórico usam SQLite em `DATA_DIR`: ótimo para uma máquina, não
  para vários servidores escrevendo no mesmo arquivo pela rede.
- **Tabelas fiscais.** Estão no YAML com a competência de cada vigência; **confira com o contador** antes de
  usar em folha real e atualize o arquivo quando a legislação mudar.
- **DIRF** foi extinta (último ano-calendário 2024); o tipo continua para ler arquivos antigos e avisa isso.

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
`DEEPSEEK_API_KEY` (Worker) e `GEMINI_API_KEY` (Revisor). Os dados ficam em `DATA_DIR` (padrão
`contabil_agente/data`).

## API

A documentação interativa (`/docs`) só fica ligada com `AGENTE_ENV=dev`. Rotas principais, todas com JWT
(`POST /token`) exceto `/health`, `/ready` e `/metrics`:

| Rota | Para quê |
|---|---|
| `POST /token`, `POST /logout`, `GET /users/me`, `POST /users` | Login, logout, usuário atual, criar usuário (admin) |
| `POST /api/chat`, `GET /api/chat/{sessao}`, `GET /api/chat/{sessao}/pdf` | Conversa, histórico e PDF do último cálculo |
| `GET /api/v1/calculo/tipos`, `POST /api/v1/calculo/{tipo}`, `POST /api/v1/calculo/{tipo}/pdf` | Cálculo direto: `rescisao`, `ferias`, `decimo_terceiro`, `inss`, `irrf`, `fgts`, `folha` |
| `GET /api/v1/documentos/tipos`, `POST /api/v1/documentos`, `POST /api/v1/documentos/lote` | Tipos aceitos, processar um arquivo, processar até 50 em segundo plano (202) |
| `POST /api/v1/rpa/fgts`, `GET /api/v1/rpa/jobs/{id}` | Pedir o extrato do FGTS (202) e acompanhar o trabalho |
| `POST /api/v1/governanca/decisoes`, `GET …/pendentes`, `GET …/decisoes/{id}`, `POST …/aprovar`, `POST …/rejeitar` | Decisões críticas assinadas e aprovação por limite |
| `GET /api/v1/lgpd/finalidades`, `POST/GET /api/v1/lgpd/consentimentos`, `DELETE /api/v1/lgpd/titular`, `GET /api/v1/lgpd/retencao`, `POST /api/v1/lgpd/retencao/executar` | Consentimento, exclusão de titular e retenção |
| `GET /api/v1/auditoria/verificar` | Confere a cadeia HMAC da sua empresa e devolve a âncora para guardar fora do servidor |
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

## RPA do FGTS

O robô (Playwright) abre o portal, **pausa** quando encontra captcha ou tela de login e espera uma pessoa
resolver na janela, depois baixa o PDF do extrato e o envia ao pipeline de documentos.

- Só baixa PDF de verdade (confere o tipo e o tamanho), calcula o SHA-256 e guarda `0600`.
- A lista de hosts permitidos é conferida de novo depois de cada redirecionamento.
- O CPF nunca vai em claro para o broker (cifrado com ML-KEM + X25519 + AES-GCM) e na auditoria só entra o hash.
- Sem captcha solver, sem flags para esconder a automação.

Como rodar:

```bash
python -m agente_v2.cli gerar-chaves-rpa --saida ./chaves   # coloque RPA_PQC_PUBLIC_KEY na API e RPA_PQC_PRIVATE_KEY no worker
playwright install chromium                                  # ou use FGTS_BROWSER_CHANNEL=msedge|chrome
celery -A contabil_agente.tarefas worker -Q rpa --pool=solo --loglevel=info
```

O worker `rpa` precisa rodar **em uma máquina com tela** (a pessoa resolve o captcha na janela) e enxergar o
mesmo `DATA_DIR` e os mesmos segredos da API (status das tarefas, auditoria e LGPD ficam em arquivos ali). O
caminho mais simples é rodar API e worker no mesmo computador. Ele **não** está no `docker-compose.yml`, de
propósito. Configuração do portal: `FGTS_CAIXA_URL`, `FGTS_PORTAL_CONFIG` (YAML com seletores e tempos),
`FGTS_BROWSER_CHANNEL`, `FGTS_BROWSER_USER_DATA_DIR`.

## Segurança e LGPD

- **Tenant isolado:** cada consulta carrega o `tenant_id` do token; acessar dado de outra empresa dá 404/403
  (testado contra IDOR).
- **Sem segredo no código:** um teste varre os arquivos versionados atrás de chaves e dados de execução.
- **Cabeçalhos:** CSP restritiva, `X-Content-Type-Options`, `Referrer-Policy`, CORS por lista (`ALLOWED_ORIGINS`),
  HSTS com `HTTPS_ONLY=1`, limite de tamanho do corpo JSON.
- **Gateway:** nginx com TLS (443) e mTLS obrigatório na 8443 (`ssl_verify_client on`); identidade enviada pelo
  cliente nunca é repassada; `/metrics` não é exposto na porta pública.
- **Auditoria verificável:** `python -m agente_v2.cli verificar-auditoria` ou `GET /api/v1/auditoria/verificar`.
  Guarde a âncora devolvida fora do servidor para detectar quem apague o fim da cadeia.
- **LGPD:** finalidades e bases legais em `contabil_agente/lgpd/`; retenção em `RETENCAO_CONFIG`; exclusão de
  titular preserva o que a lei manda guardar.

## Docker, gateway e Vault

```bash
cp .env.example .env                                  # preencha os segredos: o compose se recusa a subir sem eles
docker compose up --build                             # API (8000), worker de documentos e Redis com senha
docker compose --profile gateway up --build           # + nginx: https://localhost e mTLS em :8443 (certificados em ./certs)
docker compose --profile dev up --build               # + Vault em modo dev (nunca em produção)
```

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
├── cli.py, logging_setup.py
├── web/                    interface (index.html, app.css, app.js)
└── tests/                  API, Vault, mTLS, assinatura e front-end (navegador real)

contabil_agente/            domínio e serviços
├── calc/                   motor de cálculo (Decimal) e tabelas YAML
├── chat/                   motor da conversa, LLM, armazenamento
├── intelligence/           diálogo de cálculo, extração, auditoria forense, FSM
├── documentos/             leitura, 27 tipos, validadores, PDF
├── pipeline/               dispatcher, agentes, anomalias, evidência, destinos
├── rpa/                    robô do FGTS, pausa humana, estado das tarefas
├── tarefas/                Celery (filas documentos e rpa)
├── security/               auth, RBAC, auditoria WORM, PQC, Vault, criptografia
├── lgpd/                   base legal, consentimento, retenção, anonimização
├── middleware/             autenticação, cabeçalhos, limite de uso, métricas
├── resilience/             circuit breaker, retry, timeouts, readiness
├── governance/ governance_manager.py   decisões assinadas e aprovação
├── core/, config/, tools/, models/, utils/, orchestrator/
└── tests/                  testes de cálculo, pipeline, RPA, LGPD, infraestrutura…

rules/compliance_rules.yaml regras de conformidade
Dockerfile, docker-compose.yml, nginx/, deploy/, .github/workflows/ci.yml
```

## Testes

```bash
pip install -r requirements-dev.txt
playwright install chromium            # os testes do RPA e do front-end usam um navegador de verdade
pytest
flake8 agente_v2 contabil_agente --select=E9,F63,F7,F82,F401,F811,F841,F541
```

A suíte cobre o motor de cálculo (inclusive cenários conferidos à mão), a API e o isolamento entre empresas, o
robô contra um portal falso local, o front-end em navegador real, a cadeia de auditoria (adulteração e
truncamento), LGPD, governança, criptografia e a consistência da infraestrutura. O CI (`.github/workflows/ci.yml`)
roda lint, testes, `pip-audit` e a construção da imagem.

## Licença

[MIT](LICENSE)
