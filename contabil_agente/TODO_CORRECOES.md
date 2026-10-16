# TODO - Correções no Agente de IA

## 1. Refinar o prompt do sistema (core/prompts.py)

- [ ] Adicionar instruções para respostas estruturadas (usar markdown, listas)
- [ ] Incluir etapas de confirmação antes de ações importantes
- [ ] Reforçar tom profissional mantendo o humano

## 2. Adicionar validação de entrada (services/chat_service.py)

- [ ] Criar função para validar CPF
- [ ] Criar função para validar datas
- [ ] Criar função para validar nomes
- [ ] Integrar validações no processamento de mensagens

## 3. Criar modelos de resposta (novo arquivo services/response_templates.py)

- [ ] Template para solicitações de dados
- [ ] Template para confirmações de ação
- [ ] Template para geração de documentos
- [ ] Template para erros de validação

## 4. Testes com mais exemplos

- [ ] Criar arquivo de testes para validações
- [ ] Testar padrões de erro de digitação
- [ ] Testar casos extremos (datas inválidas, CPFs incorretos)

## 5. Loop de feedback do usuário (index_adapted.html)

- [ ] Adicionar botões de avaliação (bom/ruim) nas respostas
- [ ] Adicionar campo para comentários
- [ ] Integrar com endpoint de feedback
