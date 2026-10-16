# -*- coding: utf-8 -*-
"""
Configuração de tipos de documentos para o chat conversacional.
Define os campos necessários para cada tipo de documento/cálculo.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

# =============================================================================
# FUNÇÕES DE EXTRAÇÃO DE DADOS
# =============================================================================


def extrair_nome(texto: str) -> Optional[str]:
    """Extrai nome de pessoa do texto."""
    # Padrão 0: "nome é X" ou "o nome é X"
    m = re.search(
        r"(?:o\s+)?nome\s+(?:[eé]\s+)?([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,4})(?:\s*,|\s+CPF|\s+cpf|\s+ele|\s+ela|\s+do\s+|\s+está|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        nome = m.group(1).strip()
        # Filtrar se o nome contém palavras-chave
        if not re.search(
            r"\b(quero|gerar|preciso|fazer|rescis|transfer|ferias|documento)\b",
            nome,
            re.IGNORECASE,
        ):
            return nome
    # Padrão 1: nome: X ou nome X
    m = re.search(
        r"nome[:\s]+([A-Z][A-Za-zÀ-ÿ\s]{2,30}?)(?:\s*,|\s*$|\s+CPF|\s+cpf)",
        texto,
        re.IGNORECASE,
    )
    if m:
        nome = m.group(1).strip()
        if not re.search(
            r"\b(quero|gerar|preciso|fazer|rescis|transfer|ferias|documento)\b",
            nome,
            re.IGNORECASE,
        ):
            return nome
    # Padrão 2: para o funcionário X
    m = re.search(
        r"(?:para\s+o\s+)?funcion[aá]rio\s+([A-Z][A-Za-zÀ-ÿ\s]{2,30}?)(?:\s*,|\s+CPF|\s+cpf|\s+do\s+posto|\s+que|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # Padrão 3: Nome antes de CPF
    m = re.search(
        r"(?:para|transferir|do|da)\s+([A-Z][A-Za-zÀ-ÿ\s]{2,30}?)\s+CPF",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # Padrão 4: "rescisão para X" ou "rescisao para X" (específico)
    m = re.search(
        r"rescis[aã]o\s+(?:para|do|da)\s+([A-Z][A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,3})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # Padrão 5: "é pro/pra/para X" informal (limitado a 4 palavras)
    m = re.search(
        r"(?:[eé]\s+)?(?:pro|pra|para)\s+([A-Za-z\u00C0-\u017F]+(?:\s+[A-Za-z\u00C0-\u017F]+){0,3})",
        texto,
        re.IGNORECASE,
    )
    if m:
        nome = m.group(1).strip()
        # Verificar se não é um lugar ou palavra-chave
        if not re.search(
            r"^(posto|filial|local|norte|sul|leste|oeste|centro|gerar|fazer|criar|quero|preciso)$",
            nome,
            re.IGNORECASE,
        ):
            return nome
    return None


def extrair_cpf(texto: str) -> Optional[str]:
    """Extrai CPF do texto."""
    m = re.search(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b", texto)
    return m.group(1) if m else None


def extrair_salario(texto: str) -> Optional[str]:
    """Extrai valor de salário do texto."""
    # Padrões: R$ 2.500,00 ou R$2500 ou salário 2500 ou 2.500 reais
    m = re.search(r"R?\$\s*([\d\.,]+)", texto)
    if m:
        return m.group(1).replace(".", "").replace(",", ".")
    m = re.search(r"sal[aá]rio\s+(?:de\s+)?(?:R\$\s*)?([\d\.,]+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).replace(".", "").replace(",", ".")
    m = re.search(r"([\d\.,]+)\s*(?:reais|real)", texto, re.IGNORECASE)
    if m:
        return m.group(1).replace(".", "").replace(",", ".")
    return None


def extrair_data(texto: str) -> Optional[str]:
    """Extrai data do texto."""
    m = re.search(r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})", texto)
    return m.group(1) if m else None


def extrair_data_admissao(texto: str) -> Optional[str]:
    """Extrai data de admissão do texto."""
    m = re.search(
        r"admiss[aã]o\s+(?:em\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(
        r"admitido\s+(?:em\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(
        r"entrou\s+(?:em\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def extrair_data_demissao(texto: str) -> Optional[str]:
    """Extrai data de demissão/rescisão do texto."""
    m = re.search(
        r"(?:demiss[aã]o|rescis[aã]o|desligamento|saiu)\s+(?:em\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def extrair_cargo(texto: str) -> Optional[str]:
    """Extrai cargo/função do texto."""
    m = re.search(
        r"cargo\s+(?:de\s+)?([A-Za-zÀ-ÿ\s]+?)(?:\s*,|\s+com|\s+sal[aá]rio|\s+CPF|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        r"fun[çc][aã]o\s+(?:de\s+)?([A-Za-zÀ-ÿ\s]+?)(?:\s*,|\s+com|\s+sal[aá]rio|\s+CPF|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(?:trabalha|atua)\s+como\s+([A-Za-zÀ-ÿ\s]+?)(?:\s*,|\s+com|\s+sal[aá]rio|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def extrair_motivo_demissao(texto: str) -> Optional[str]:
    """Extrai tipo/motivo da demissão."""
    texto_lower = texto.lower()
    if "justa causa" in texto_lower:
        return "justa_causa"
    if "pediu demiss" in texto_lower or "pedido de demiss" in texto_lower:
        return "pedido_funcionario"
    if "sem justa" in texto_lower:
        return "sem_justa_causa"
    if "acordo" in texto_lower or "consensual" in texto_lower:
        return "acordo_mutuo"
    return None


def extrair_aviso_previo(texto: str) -> Optional[str]:
    """Extrai tipo de aviso prévio."""
    texto_lower = texto.lower()
    if "aviso indenizado" in texto_lower or "indenizar aviso" in texto_lower:
        return "indenizado"
    if "aviso trabalhado" in texto_lower or "trabalhar aviso" in texto_lower:
        return "trabalhado"
    if "sem aviso" in texto_lower or "dispensa aviso" in texto_lower:
        return "dispensado"
    return None


def extrair_dias_ferias(texto: str) -> Optional[int]:
    """Extrai quantidade de dias de férias."""
    m = re.search(r"(\d+)\s*dias?\s*(?:de\s+)?f[eé]rias", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"f[eé]rias\s+(?:de\s+)?(\d+)\s*dias?", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def extrair_periodo_aquisitivo(texto: str) -> Optional[str]:
    """Extrai período aquisitivo das férias."""
    m = re.search(
        r"per[ií]odo\s+(?:aquisitivo\s+)?(\d{4}[/\-]\d{4}|\d{2}[/\-]\d{2})",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def extrair_abono_pecuniario(texto: str) -> bool:
    """Verifica se quer abono pecuniário (vender férias)."""
    texto_lower = texto.lower()
    return "abono" in texto_lower or "vender" in texto_lower or "1/3" in texto_lower


def extrair_local_origem(texto: str) -> Optional[str]:
    """Extrai local de origem para transferência."""
    patterns = [
        r"(?:do\s+(?:posto|local|filial))\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
        r"(?:está\s+no\s+(?:posto|local)?)\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
        r"(?:atual(?:mente)?|atualmente?\s+(?:no|em))\s+(?:posto|local)?\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extrair_local_destino(texto: str) -> Optional[str]:
    """Extrai local de destino para transferência."""
    patterns = [
        r"(?:vai\s+(?:pro|para\s+o?|para))\s+(?:posto|filial|unidade|local)?\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
        r"(?:pro|para\s+o?)\s+(?:posto|filial|unidade|local)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
        r"(?:novo\s+(?:posto|local|filial))[:\s]+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extrair_mes_referencia(texto: str) -> Optional[str]:
    """Extrai mês de referência para folha/13º."""
    meses = {
        "janeiro": "01",
        "fevereiro": "02",
        "março": "03",
        "marco": "03",
        "abril": "04",
        "maio": "05",
        "junho": "06",
        "julho": "07",
        "agosto": "08",
        "setembro": "09",
        "outubro": "10",
        "novembro": "11",
        "dezembro": "12",
    }
    texto_lower = texto.lower()
    for mes, num in meses.items():
        if mes in texto_lower:
            # Tentar pegar o ano
            m = re.search(rf"{mes}\s*(?:de\s+)?(\d{{4}})?", texto_lower)
            ano = m.group(1) if m and m.group(1) else str(datetime.now().year)
            return f"{num}/{ano}"
    # Formato numérico: 03/2026 ou 2026/03
    m = re.search(r"(\d{1,2})[/\-](\d{4})", texto)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2)}"
    return None


def extrair_horas_extras(texto: str) -> Optional[float]:
    """Extrai quantidade de horas extras."""
    m = re.search(r"(\d+(?:[,\.]\d+)?)\s*(?:horas?\s+)?extras?", texto, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def extrair_faltas(texto: str) -> Optional[int]:
    """Extrai quantidade de faltas."""
    m = re.search(r"(\d+)\s*faltas?", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"faltou\s+(\d+)\s*dias?", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def extrair_dependentes(texto: str) -> Optional[int]:
    """Extrai número de dependentes."""
    m = re.search(r"(\d+)\s*dependentes?", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"dependentes?\s*[:=]?\s*(\d+)", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def extrair_empresa(texto: str) -> Optional[str]:
    """Extrai nome da empresa."""
    m = re.search(
        r"empresa\s+([A-Za-zÀ-ÿ\s\.\&]+?)(?:\s*,|\s+CNPJ|\s+com|\s*$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def extrair_cnpj(texto: str) -> Optional[str]:
    """Extrai CNPJ."""
    m = re.search(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})\b", texto)
    return m.group(1) if m else None


# =============================================================================
# DEFINIÇÃO DOS TIPOS DE DOCUMENTOS
# =============================================================================

TIPOS_DOCUMENTO = {
    # -------------------------------------------------------------------------
    # RESCISÃO
    # -------------------------------------------------------------------------
    "rescisao": {
        "nome_display": "Rescisão Trabalhista",
        "contexto_var": "aguardando_dados_rescisao",
        "campos_obrigatorios": [
            "nome",
            "cpf",
            "salario",
            "data_admissao",
            "data_demissao",
        ],
        "campos_opcionais": ["cargo", "motivo_demissao", "aviso_previo", "dependentes"],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "salario": extrair_salario,
            "data_admissao": extrair_data_admissao,
            "data_demissao": extrair_data_demissao,
            "cargo": extrair_cargo,
            "motivo_demissao": extrair_motivo_demissao,
            "aviso_previo": extrair_aviso_previo,
            "dependentes": extrair_dependentes,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "salario": "salário",
            "data_admissao": "data de admissão",
            "data_demissao": "data de demissão/rescisão",
            "cargo": "cargo/função",
            "motivo_demissao": "motivo da demissão (justa causa, sem justa causa, pedido, acordo)",
            "aviso_previo": "tipo de aviso prévio (indenizado, trabalhado ou dispensado)",
            "dependentes": "número de dependentes",
        },
    },
    # -------------------------------------------------------------------------
    # FÉRIAS
    # -------------------------------------------------------------------------
    "ferias": {
        "nome_display": "Cálculo de Férias",
        "contexto_var": "aguardando_dados_ferias",
        "campos_obrigatorios": ["nome", "cpf", "salario"],
        "campos_opcionais": [
            "dias_ferias",
            "periodo_aquisitivo",
            "abono_pecuniario",
            "data_inicio",
            "dependentes",
        ],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "salario": extrair_salario,
            "dias_ferias": extrair_dias_ferias,
            "periodo_aquisitivo": extrair_periodo_aquisitivo,
            "abono_pecuniario": extrair_abono_pecuniario,
            "data_inicio": extrair_data,
            "dependentes": extrair_dependentes,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "salario": "salário",
            "dias_ferias": "quantidade de dias de férias (padrão: 30)",
            "periodo_aquisitivo": "período aquisitivo (ex: 2025/2026)",
            "abono_pecuniario": "se quer vender parte das férias (abono pecuniário)",
            "data_inicio": "data de início das férias",
            "dependentes": "número de dependentes",
        },
    },
    # -------------------------------------------------------------------------
    # 13º SALÁRIO
    # -------------------------------------------------------------------------
    "decimo_terceiro": {
        "nome_display": "13º Salário",
        "contexto_var": "aguardando_dados_decimo",
        "campos_obrigatorios": ["nome", "cpf", "salario"],
        "campos_opcionais": [
            "meses_trabalhados",
            "data_admissao",
            "faltas",
            "dependentes",
        ],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "salario": extrair_salario,
            "meses_trabalhados": lambda t: (
                int(m.group(1))
                if (m := re.search(r"(\d+)\s*meses?", t, re.IGNORECASE))
                else None
            ),
            "data_admissao": extrair_data_admissao,
            "faltas": extrair_faltas,
            "dependentes": extrair_dependentes,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "salario": "salário",
            "meses_trabalhados": "meses trabalhados no ano (se não for o ano todo)",
            "data_admissao": "data de admissão",
            "faltas": "quantidade de faltas no período",
            "dependentes": "número de dependentes",
        },
    },
    # -------------------------------------------------------------------------
    # FOLHA DE PAGAMENTO
    # -------------------------------------------------------------------------
    "folha_pagamento": {
        "nome_display": "Folha de Pagamento",
        "contexto_var": "aguardando_dados_folha",
        "campos_obrigatorios": ["nome", "cpf", "salario", "mes_referencia"],
        "campos_opcionais": [
            "cargo",
            "horas_extras",
            "faltas",
            "dependentes",
            "descontos",
            "beneficios",
        ],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "salario": extrair_salario,
            "mes_referencia": extrair_mes_referencia,
            "cargo": extrair_cargo,
            "horas_extras": extrair_horas_extras,
            "faltas": extrair_faltas,
            "dependentes": extrair_dependentes,
            "descontos": extrair_salario,  # Reutiliza extrator de valor
            "beneficios": extrair_salario,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "salario": "salário base",
            "mes_referencia": "mês de referência (ex: março/2026)",
            "cargo": "cargo/função",
            "horas_extras": "horas extras (se houver)",
            "faltas": "faltas no mês (se houver)",
            "dependentes": "número de dependentes",
            "descontos": "outros descontos",
            "beneficios": "benefícios (VT, VR, etc)",
        },
    },
    # -------------------------------------------------------------------------
    # TRANSFERÊNCIA
    # -------------------------------------------------------------------------
    "transferencia": {
        "nome_display": "Aditivo de Transferência",
        "contexto_var": "aguardando_dados_transferencia",
        "campos_obrigatorios": ["nome", "cpf", "local_destino"],
        "campos_opcionais": ["local_origem", "data_transferencia", "cargo", "empresa"],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "local_origem": extrair_local_origem,
            "local_destino": extrair_local_destino,
            "data_transferencia": extrair_data,
            "cargo": extrair_cargo,
            "empresa": extrair_empresa,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "local_origem": "posto/local atual",
            "local_destino": "novo posto/local",
            "data_transferencia": "data da transferência",
            "cargo": "cargo/função",
            "empresa": "nome da empresa",
        },
    },
    # -------------------------------------------------------------------------
    # ADMISSÃO
    # -------------------------------------------------------------------------
    "admissao": {
        "nome_display": "Admissão de Funcionário",
        "contexto_var": "aguardando_dados_admissao",
        "campos_obrigatorios": ["nome", "cpf", "cargo", "salario", "data_admissao"],
        "campos_opcionais": ["empresa", "cnpj", "dependentes", "horario_trabalho"],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "cargo": extrair_cargo,
            "salario": extrair_salario,
            "data_admissao": extrair_data_admissao,
            "empresa": extrair_empresa,
            "cnpj": extrair_cnpj,
            "dependentes": extrair_dependentes,
            "horario_trabalho": lambda t: (
                re.search(r"(\d{1,2}:\d{2})\s*[aà-]\s*(\d{1,2}:\d{2})", t).groups()
                if re.search(r"(\d{1,2}:\d{2})\s*[aà-]\s*(\d{1,2}:\d{2})", t)
                else None
            ),
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "cargo": "cargo/função",
            "salario": "salário",
            "data_admissao": "data de admissão",
            "empresa": "nome da empresa",
            "cnpj": "CNPJ da empresa",
            "dependentes": "número de dependentes",
            "horario_trabalho": "horário de trabalho (ex: 08:00 às 17:00)",
        },
    },
    # -------------------------------------------------------------------------
    # CÁLCULO INSS
    # -------------------------------------------------------------------------
    "inss": {
        "nome_display": "Cálculo de INSS",
        "contexto_var": "aguardando_dados_inss",
        "campos_obrigatorios": ["salario"],
        "campos_opcionais": ["nome", "cpf", "mes_referencia"],
        "extratores": {
            "salario": extrair_salario,
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "mes_referencia": extrair_mes_referencia,
        },
        "labels": {
            "salario": "salário bruto",
            "nome": "nome do funcionário (opcional)",
            "cpf": "CPF (opcional)",
            "mes_referencia": "mês de referência (opcional)",
        },
    },
    # -------------------------------------------------------------------------
    # CÁLCULO FGTS
    # -------------------------------------------------------------------------
    "fgts": {
        "nome_display": "Cálculo de FGTS",
        "contexto_var": "aguardando_dados_fgts",
        "campos_obrigatorios": ["salario"],
        "campos_opcionais": ["nome", "cpf", "mes_referencia", "meses"],
        "extratores": {
            "salario": extrair_salario,
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "mes_referencia": extrair_mes_referencia,
            "meses": lambda t: (
                int(m.group(1))
                if (m := re.search(r"(\d+)\s*meses?", t, re.IGNORECASE))
                else None
            ),
        },
        "labels": {
            "salario": "salário bruto",
            "nome": "nome do funcionário (opcional)",
            "cpf": "CPF (opcional)",
            "mes_referencia": "mês de referência (opcional)",
            "meses": "quantidade de meses (para cálculo acumulado)",
        },
    },
    # -------------------------------------------------------------------------
    # CÁLCULO IRRF
    # -------------------------------------------------------------------------
    "impostos": {
        "nome_display": "Cálculo de IRRF",
        "contexto_var": "aguardando_dados_irrf",
        "campos_obrigatorios": ["salario"],
        "campos_opcionais": ["nome", "cpf", "dependentes", "descontos_legais"],
        "extratores": {
            "salario": extrair_salario,
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "dependentes": extrair_dependentes,
            "descontos_legais": extrair_salario,
        },
        "labels": {
            "salario": "salário bruto",
            "nome": "nome do funcionário (opcional)",
            "cpf": "CPF (opcional)",
            "dependentes": "número de dependentes",
            "descontos_legais": "outros descontos legais",
        },
    },
    # -------------------------------------------------------------------------
    # HOLERITE / CONTRACHEQUE
    # -------------------------------------------------------------------------
    "holerite": {
        "nome_display": "Holerite/Contracheque",
        "contexto_var": "aguardando_dados_holerite",
        "campos_obrigatorios": ["nome", "cpf", "salario", "mes_referencia"],
        "campos_opcionais": [
            "cargo",
            "empresa",
            "horas_extras",
            "faltas",
            "dependentes",
        ],
        "extratores": {
            "nome": extrair_nome,
            "cpf": extrair_cpf,
            "salario": extrair_salario,
            "mes_referencia": extrair_mes_referencia,
            "cargo": extrair_cargo,
            "empresa": extrair_empresa,
            "horas_extras": extrair_horas_extras,
            "faltas": extrair_faltas,
            "dependentes": extrair_dependentes,
        },
        "labels": {
            "nome": "nome do funcionário",
            "cpf": "CPF",
            "salario": "salário base",
            "mes_referencia": "mês de referência",
            "cargo": "cargo/função",
            "empresa": "nome da empresa",
            "horas_extras": "horas extras",
            "faltas": "faltas",
            "dependentes": "número de dependentes",
        },
    },
}


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================


def detectar_tipo_documento(texto: str) -> str:
    """Detecta o tipo de documento a partir do texto da mensagem."""
    texto_lower = texto.lower()

    # Rescisão
    if any(
        kw in texto_lower
        for kw in ["rescis", "demis", "deslig", "mandar embora", "demitir"]
    ):
        return "rescisao"

    # Férias
    if any(kw in texto_lower for kw in ["férias", "ferias"]):
        return "ferias"

    # 13º Salário
    if any(
        kw in texto_lower
        for kw in ["13", "décimo", "decimo", "décimo terceiro", "decimo terceiro"]
    ):
        return "decimo_terceiro"

    # Folha de pagamento
    if any(
        kw in texto_lower for kw in ["folha", "pagamento", "holerite", "contracheque"]
    ):
        if "holerite" in texto_lower or "contracheque" in texto_lower:
            return "holerite"
        return "folha_pagamento"

    # Transferência
    if any(
        kw in texto_lower
        for kw in ["transfer", "aditivo", "trocar de posto", "mudar de posto"]
    ):
        return "transferencia"

    # Admissão
    if any(
        kw in texto_lower
        for kw in ["admiss", "contratar", "contratação", "novo funcionário"]
    ):
        return "admissao"

    # INSS
    if any(kw in texto_lower for kw in ["inss", "previdência", "previdencia"]):
        return "inss"

    # FGTS
    if "fgts" in texto_lower:
        return "fgts"

    # Impostos/IRRF
    if any(kw in texto_lower for kw in ["imposto", "irrf", "irpf", "ir "]):
        return "impostos"

    return "consulta"


def extrair_dados_documento(tipo_doc: str, texto: str) -> Dict[str, any]:
    """Extrai todos os dados possíveis do texto para um tipo de documento."""
    if tipo_doc not in TIPOS_DOCUMENTO:
        return {}

    config = TIPOS_DOCUMENTO[tipo_doc]
    dados = {}

    for campo, extrator in config["extratores"].items():
        try:
            valor = extrator(texto)
            if valor is not None:
                dados[campo] = valor
        except Exception:
            pass

    return dados


def verificar_dados_completos(
    tipo_doc: str, dados: Dict[str, any]
) -> tuple[bool, List[str]]:
    """
    Verifica se os dados estão completos para gerar o documento.
    Retorna (completo, lista_de_campos_faltando).
    """
    if tipo_doc not in TIPOS_DOCUMENTO:
        return True, []

    config = TIPOS_DOCUMENTO[tipo_doc]
    campos_obrigatorios = config["campos_obrigatorios"]
    faltando = []

    for campo in campos_obrigatorios:
        if campo not in dados or dados[campo] is None:
            label = config["labels"].get(campo, campo)
            faltando.append(label)

    return len(faltando) == 0, faltando


def gerar_mensagem_coleta(tipo_doc: str, dados_faltando: List[str]) -> str:
    """Gera mensagem amigável pedindo os dados faltantes."""
    if tipo_doc not in TIPOS_DOCUMENTO:
        return "Por favor, forneça mais detalhes."

    config = TIPOS_DOCUMENTO[tipo_doc]
    nome_doc = config["nome_display"]

    if len(dados_faltando) == 1:
        return f"Para gerar o {nome_doc}, só falta o(a) **{dados_faltando[0]}**. Pode me informar?"

    lista = "\n- ".join(dados_faltando)
    return f"Para gerar o {nome_doc}, preciso de mais alguns dados:\n- {lista}\n\nPode me informar?"
