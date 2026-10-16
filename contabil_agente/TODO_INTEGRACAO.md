# TODO - Integração Backend-Frontend

## Objetivo

Conectar o frontend (index_adapted.html) com o backend Flask e fazer todos os botões funcionarem.

## Problemas Identificados

1. Incompatibilidade de nomes de endpoints:
   - Frontend: `/api/analyze-documents` → Backend: `/api/analyze`
   - Frontend: `/api/text-to-speech` → Backend: `/api/tts`
2. Placeholder functions no frontend que precisam de implementação

## Tarefas

### Fase 1: Corrigir Endpoints do Backend ✅ CONCLUÍDO

- [x] 1.1 Adicionar endpoint `/api/analyze-documents` (alias para `/api/analyze`)
- [x] 1.2 Adicionar endpoint `/api/text-to-speech` (alias para `/api/tts`)
- [x] 1.3 Verificar se `/api/chat` está funcionando corretamente
- [x] 1.4 Verificar se `/api/health` está funcionando corretamente
- [x] 1.5 Verificar rota `/download/<filename>`

### Fase 2: Implementar Placeholder Functions ✅ CONCLUÍDO

- [x] 2.1 Implementar `generateSPED()` - Gera SPED via API
- [x] 2.2 Implementar `generateDCTF()` - Prepara DCTF
- [x] 2.3 Implementar `generateDIRF()` - Gera DIRF
- [x] 2.4 Implementar `runAudit()` - Executa auditoria via API
- [x] 2.5 Implementar `showSPEDGenerator()` - Interface de seleção de SPED
- [x] 2.6 Implementar `showComplianceMonitor()` - Status de conformidade via API
- [x] 2.7 Implementar `showAuditTrail()` - Logs de auditoria via API

### Fase 3: Novos Endpoints do Backend ✅ CONCLUÍDO

- [x] 3.1 `/api/sped/generate` - Gera arquivos SPED
- [x] 3.2 `/api/compliance/status` - Status de conformidade
- [x] 3.3 `/api/audit/run` - Executa auditoria
- [x] 3.4 `/api/audit/logs` - Retorna logs de auditoria
- [x] 3.5 `/api/workflows` - Lista workflows
- [x] 3.6 `/api/integrations` - Lista integrações

### Fase 4: Testar Integração ⏳ PENDENTE

- [ ] 4.1 Iniciar servidor backend
- [ ] 4.2 Testar conexão frontend-backend
- [ ] 4.3 Testar envio de mensagens via chat
- [ ] 4.4 Testar geração de SPED
- [ ] 4.5 Testar auditoria
- [ ] 4.6 Testar download de documentos

## Endpoints Disponíveis no Backend

```bash
POST /api/chat              → Chat principal (IA)
GET  /api/health            → Health check
POST /api/transcribe        → Transcrição de áudio
POST /api/analyze-documents → Análise de documentos
POST /api/text-to-speech   → Conversão texto para áudio
GET  /download/<filename>   → Download de documentos
POST /api/sped/generate     → Gera SPED
GET  /api/compliance/status → Status de conformidade
POST /api/audit/run         → Executa auditoria
GET  /api/audit/logs        → Logs de auditoria
GET  /api/workflows         → Lista workflows
GET  /api/integrations      → Lista integrações
```

## Status

✅ Backend atualizado com novos endpoints
✅ Frontend conectado com APIs
⏳ Aguardando testes de integração

## Como Testar

```bash
# 1. Iniciar o servidor
cd contabil_agente
python app.py

# 2. Abrir no navegador
# Acesse http://localhost:5000

# 3. Testar os botões
# - "Gerar SPED" → deve chamar /api/sped/generate
# - "Monitor de Conformidade" → deve mostrar status via /api/compliance/status
# - "Auditoria Interna" → deve executar auditoria via /api/audit/run
```
