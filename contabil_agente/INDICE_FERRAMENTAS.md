# 📚 Índice de Ferramentas - Referência Rápida

## 🎯 Visão Geral

**Total de Ferramentas:** 9
**Status:** ✅ Todas testadas e validadas
**Testes:** 17/17 passaram

---

## 🧮 1. ToolCalculo

**Arquivo:** `tools/calculo_tool.py`  
**Propósito:** Cálculos trabalhistas e tributários (INSS/IRRF 2026)  
**Criticidade:** 🔥 **CRÍTICO** (não alterar lógica)

### Métodos Principais:
```python
from contabil_agente.tools import ToolCalculo

calc = ToolCalculo()

# INSS Progressivo (4 faixas)
inss = calc.calcular_inss(Decimal("5000"))  # R$ 533,18

# IRRF Progressivo (5 faixas)
irrf = calc.calcular_irrf(Decimal("4466.82"))  # R$ 342,26

# Rescisão Completa
resultado = calc.calcular_rescisao_completa(funcionario, rescisao)
```

### Características:
- ✅ Tabelas oficiais 2026
- ✅ Atualização automática (2h AM) via APScheduler
- ✅ 4 faixas INSS: 7.5%, 9%, 12%, 14%
- ✅ 5 faixas IRRF: 0%, 7.5%, 15%, 22.5%, 27.5%
- ✅ Validação profissional (escritório contábil)

---

## 📄 2. ToolPDF

**Arquivo:** `tools/pdf_tool.py`  
**Propósito:** Geração de documentos PDF profissionais

### Métodos Principais:
```python
from contabil_agente.tools import ToolPDF

pdf = ToolPDF()

# Gerar TRCT
resultado = pdf.gerar_trct(dados_rescisao)
# Retorna: {"filepath": "TRCT_12345_20260128.pdf", ...}

# Gerar Holerite
resultado = pdf.gerar_holerite(dados_pagamento)

# Adicionar página de assinatura
resultado = pdf.adicionar_pagina_assinatura(pdf_path)

# Listar documentos
documentos = pdf.listar_documentos(filtro="TRCT")
```

### Documentos Suportados:
- ✅ TRCT (Termo de Rescisão)
- ✅ Holerite (Contracheque)
- ✅ Contratos de Trabalho
- ✅ Recibos diversos

---

## 🔐 3. ToolAssinatura

**Arquivo:** `tools/assinatura_tool.py`  
**Propósito:** Assinatura digital com HMAC-SHA256

### Métodos Principais:
```python
from contabil_agente.tools import ToolAssinatura

assinatura = ToolAssinatura()

# Assinar documento
resultado = assinatura.assinar_documento(
    filepath="documento.pdf",
    assinante={"nome": "João", "cpf": "123.456.789-00", "tipo": "funcionario"}
)
# Retorna: {"signature_id": "abc123...", "doc_hash": "sha256..."}

# Verificar assinatura
resultado = assinatura.verificar_assinatura(signature_id, filepath)
# Retorna: {"valida": True/False, "detalhes": {...}}

# Múltiplas assinaturas (TRCT - funcionário + empresa)
resultado = assinatura.assinar_multiplos(filepath, [assinante1, assinante2])
```

### Características:
- ✅ HMAC-SHA256 seguro
- ✅ Registro em governança
- ✅ Detecção de alterações
- ✅ Suporte múltiplas assinaturas

---

## 🎤 4. ToolVoz

**Arquivo:** `tools/voz_tool.py`  
**Propósito:** STT (Speech-to-Text) e TTS (Text-to-Speech)

### Métodos Principais:
```python
from contabil_agente.tools import ToolVoz

voz = ToolVoz()

# Transcrever do microfone
resultado = voz.transcrever_microfone(timeout=5, language="pt-BR")
# Retorna: {"texto": "olá como vai", ...}

# Transcrever arquivo de áudio
resultado = voz.transcrever_arquivo("audio.wav")

# Sintetizar voz
resultado = voz.sintetizar_voz("Olá, bem-vindo!", salvar_arquivo=True)
# Retorna: {"filepath": "tts_20260128.mp3", ...}

# Listar vozes disponíveis
vozes = voz.listar_vozes_disponiveis()

# Configurar velocidade
voz.configurar_velocidade(wpm=180)  # Palavras por minuto
```

### Características:
- ✅ Google Speech Recognition (STT)
- ✅ pyttsx3 (TTS)
- ✅ Múltiplas vozes e idiomas
- ✅ Thread-safe (TTS_LOCK)

---

## 💼 5. ToolEncargosPatronais

**Arquivo:** `tools/encargos_tool.py`  
**Propósito:** Cálculo de encargos patronais (empresa)

### Métodos Principais:
```python
from contabil_agente.tools import ToolEncargosPatronais

encargos = ToolEncargosPatronais()

# Calcular encargos completos
resultado = encargos.calcular_encargos_completos(
    salario_bruto=5000,
    atividade_empresa="servicos"
)
# Retorna: {
#   "total_encargos": 1865.00,
#   "percentual_total": 37.30%,
#   "encargos": {"inss_patronal": 1000, "rat": 50, "terceiros": 290, ...}
# }

# Calcular folha de pagamento completa
resultado = encargos.calcular_folha_pagamento_total(funcionarios, atividade)

# Provisão 13º e férias
resultado = encargos.calcular_provisao_13_ferias(salario, meses=12)
```

### Encargos Calculados:
- ✅ INSS Patronal: 20%
- ✅ RAT: 1-3% (conforme atividade)
- ✅ Sistema S: 5.8%
- ✅ FGTS: 8%
- ✅ Salário Educação: 2.5%

---

## 👔 6. ToolProLabore

**Arquivo:** `tools/prolabore_tool.py`  
**Propósito:** Cálculo de pró-labore de sócios

### Métodos Principais:
```python
from contabil_agente.tools import ToolProLabore

prolabore = ToolProLabore()

# Calcular pró-labore completo
resultado = prolabore.calcular_prolabore_completo(
    valor_prolabore=5000,
    dependentes_irrf=1,
    outras_deducoes=0
)
# Retorna: {
#   "prolabore_bruto": 5000,
#   "valor_liquido": 4154.18,
#   "descontos": {"inss": 550, "irrf": 295.82, ...}
# }

# Múltiplos sócios
resultado = prolabore.calcular_multiplos_socios([socio1, socio2])

# Simulação baseada em faturamento
resultado = prolabore.simular_prolabore_ideal(
    faturamento_mensal=20000,
    percentual_retirada=0.30
)
```

### Características:
- ✅ INSS 11% (contribuinte individual)
- ✅ Teto INSS: R$ 8.157,41
- ✅ IRRF tabela progressiva
- ✅ Alertas: acima do teto, abaixo do mínimo

---

## 📑 7. ToolGPS

**Arquivo:** `tools/gps_tool.py`  
**Propósito:** Geração de Guias da Previdência Social (INSS)

### Métodos Principais:
```python
from contabil_agente.tools import ToolGPS

gps = ToolGPS()

# Gerar GPS
resultado = gps.gerar_gps(
    codigo_pagamento="2100",  # Contribuinte Individual
    competencia="01/2026",
    valor=550,
    identificador="12345678000190",
    nome_contribuinte="Empresa LTDA"
)
# Retorna: {"gps_id": "GPS_2100_012026_...", "vencimento": "20/02/2026", ...}

# GPS específica para empresa (INSS Patronal)
resultado = gps.gerar_gps_empresa(cnpj, razao_social, competencia, valor_inss)

# Marcar como paga
gps.marcar_como_paga(gps_id, "15/02/2026")

# Listar pendentes
pendentes = gps.listar_gps_pendentes(mes_competencia="01/2026")
```

### Códigos Suportados:
- ✅ 2100: Contribuinte Individual
- ✅ 2011: Empresa (INSS Patronal)
- ✅ 1007: Autônomo
- ✅ 1120: Empregador Doméstico

---

## 🏛️ 8. ToolDARF

**Arquivo:** `tools/darf_tool.py`  
**Propósito:** Geração de DARF (impostos federais)

### Métodos Principais:
```python
from contabil_agente.tools import ToolDARF

darf = ToolDARF()

# Gerar DARF
resultado = darf.gerar_darf(
    codigo_receita="0561",  # IRRF
    competencia="01/2026",
    valor_principal=342.26,
    valor_multa=0,
    valor_juros=0,
    cnpj="12345678000190"
)
# Retorna: {"darf_id": "DARF_0561_012026_...", "vencimento": "20/02/2026", ...}

# DARF específica para IRRF
resultado = darf.gerar_darf_irrf(competencia, valor_irrf, cnpj, razao_social)

# PIS + COFINS (gera 2 DARFs)
resultado = darf.gerar_darf_pis_cofins(competencia, valor_pis, valor_cofins, cnpj, razao_social)

# Listar pendentes
pendentes = darf.listar_darfs_pendentes(mes_competencia="01/2026", codigo_receita="0561")
```

### Códigos Suportados:
- ✅ 0561: IRRF
- ✅ 8109: PIS
- ✅ 2172: COFINS
- ✅ 2469: CSLL
- ✅ 0190: IRPJ
- ✅ 6015: Simples Nacional

---

## 📋 9. ToolAdmissao

**Arquivo:** `tools/admissao_tool.py`  
**Propósito:** Gerenciamento de processos de admissão

### Métodos Principais:
```python
from contabil_agente.tools import ToolAdmissao

admissao = ToolAdmissao()

# Criar processo de admissão
resultado = admissao.criar_processo_admissao({
    "nome": "João Silva",
    "cpf": "123.456.789-00",
    "cargo": "Analista",
    "data_admissao": "01/02/2026",
    "salario": 5000,
    "departamento": "TI"
})
# Retorna: {"processo_id": "ADM_12345678900_...", "total_documentos": 14, ...}

# Atualizar documento
admissao.atualizar_documento(processo_id, "CPF", "entregue", "Original e cópia ok")

# Concluir etapa
admissao.concluir_etapa(processo_id, "Exame médico admissional", "RH")

# Obter status
status = admissao.obter_status_processo(processo_id)
# Retorna: {"progresso": {"percentual_geral": 45.5}, "pendencias": [...], ...}

# Listar admissões pendentes
pendentes = admissao.listar_admissoes_pendentes()
```

### Checklist Automático:
- ✅ 14 documentos obrigatórios
- ✅ 9 etapas do processo (ASO, eSocial, CTPS, benefícios, integração)
- ✅ Acompanhamento de progresso
- ✅ Identificação de pendências

---

## 🔧 Como Usar

### Importação Geral:
```python
from contabil_agente.tools import (
    ToolCalculo,
    ToolPDF,
    ToolAssinatura,
    ToolVoz,
    ToolEncargosPatronais,
    ToolProLabore,
    ToolGPS,
    ToolDARF,
    ToolAdmissao
)
```

### Exemplo Completo (Rescisão + PDF + Assinatura):
```python
from decimal import Decimal
from contabil_agente.tools import ToolCalculo, ToolPDF, ToolAssinatura, DadosFuncionario, DadosRescisaoCalculo

# 1. Calcula rescisão
calc = ToolCalculo()
funcionario = DadosFuncionario(
    nome="Maria Santos",
    cpf="123.456.789-00",
    cargo="Analista",
    salario_base=Decimal("5000"),
    data_admissao="01/01/2023",
    data_demissao="28/01/2026"
)
rescisao = DadosRescisaoCalculo(tipo="sem_justa_causa", meses_trabalhados_total=36)
calc.aplicar_regras_por_tipo_rescisao("sem_justa_causa", rescisao)
resultado_calculo = calc.calcular_rescisao_completa(funcionario, rescisao)

# 2. Gera PDF
pdf = ToolPDF()
resultado_pdf = pdf.gerar_trct({
    "nome": funcionario.nome,
    "cpf": funcionario.cpf,
    "cargo": funcionario.cargo,
    "data_admissao": funcionario.data_admissao,
    "data_demissao": funcionario.data_demissao,
    "tipo": "sem_justa_causa",
    "verbas": resultado_calculo["detalhes"],
    "empresa": {"razao_social": "Empresa LTDA", "cnpj": "12.345.678/0001-90"}
})

# 3. Assina digitalmente
assinatura = ToolAssinatura()
assinantes = [
    {"nome": "Maria Santos", "cpf": "123.456.789-00", "tipo": "funcionario"},
    {"nome": "Empresa LTDA", "cpf": "12.345.678/0001-90", "tipo": "empresa"}
]
resultado_assinatura = assinatura.assinar_multiplos(resultado_pdf["filepath"], assinantes)

print(f"✅ TRCT gerado: {resultado_pdf['filepath']}")
print(f"✅ Assinaturas: {len(resultado_assinatura['assinaturas'])}")
```

---

## 📊 Estatísticas

| Ferramenta | Linhas de Código | Métodos Públicos | Complexidade |
|------------|------------------|------------------|--------------|
| ToolCalculo | 1.200+ | 15+ | 🔥 Alta |
| ToolPDF | 450 | 4 | Média |
| ToolAssinatura | 300 | 5 | Baixa |
| ToolVoz | 350 | 7 | Média |
| ToolEncargosPatronais | 300 | 3 | Média |
| ToolProLabore | 350 | 4 | Média |
| ToolGPS | 250 | 5 | Baixa |
| ToolDARF | 300 | 6 | Baixa |
| ToolAdmissao | 350 | 5 | Média |
| **TOTAL** | **~3.850** | **54** | - |

---

## 🧪 Validação

Execute o script de validação:
```bash
python validar_ferramentas.py
```

**Resultado Esperado:** 9/9 testes passam ✅

---

## 📝 Notas Importantes

1. **ToolCalculo é CRÍTICO**: Não alterar lógica de cálculo INSS/IRRF 2026
2. **Thread-Safety**: ToolVoz usa TTS_LOCK global
3. **Auditoria**: Todas as ferramentas chamam `send_audit()`
4. **Diretórios**: Criados automaticamente em `documents/`
5. **Validação**: Sempre execute `validar_ferramentas.py` após mudanças

---

**📚 Veja também:**
- [MODULAR_README.md](MODULAR_README.md) - Arquitetura completa
- [GUIA_MIGRACAO.md](GUIA_MIGRACAO.md) - Como integrar ao código existente
- [RESUMO_REFATORACAO.md](RESUMO_REFATORACAO.md) - Status do projeto
