"""
Configuração Multi-Tenant - 15 Empresas
"""

import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class EmpresaConfig:
    id: str
    nome: str
    db_path: str
    ai_model: str
    ai_temperature: float
    max_tokens: int
    api_key: str
    assistente_nome: str
    logo_path: str
    rate_limit: str


# Configuração de 15 empresas
EMPRESAS: Dict[str, EmpresaConfig] = {
    "elite_senior": EmpresaConfig(
        id="elite_senior",
        nome="Elite Sênior Consultoria",
        db_path="db/elite_senior_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1500,
        api_key=os.getenv("API_KEY_ELITE_SENIOR", "key_elite_001"),
        assistente_nome="Maria Helena",
        logo_path="static/logos/elite_senior.png",
        rate_limit="100/hour",
    ),
    "contabil_abc": EmpresaConfig(
        id="contabil_abc",
        nome="Contábil ABC Ltda",
        db_path="db/contabil_abc_sessions.db",
        ai_model="llama-3.1-8b-instant",
        ai_temperature=0.5,
        max_tokens=1000,
        api_key=os.getenv("API_KEY_CONTABIL_ABC", "key_abc_002"),
        assistente_nome="João Carlos",
        logo_path="static/logos/contabil_abc.png",
        rate_limit="50/hour",
    ),
    "fiscal_pro": EmpresaConfig(
        id="fiscal_pro",
        nome="Fiscal Pro Consultoria",
        db_path="db/fiscal_pro_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.2,
        max_tokens=2000,
        api_key=os.getenv("API_KEY_FISCAL_PRO", "key_fiscal_003"),
        assistente_nome="Dra. Patricia",
        logo_path="static/logos/fiscal_pro.png",
        rate_limit="200/hour",
    ),
    "empresa_04": EmpresaConfig(
        id="empresa_04",
        nome="Contabilidade Souza & Cia",
        db_path="db/empresa_04_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1500,
        api_key=os.getenv("API_KEY_EMPRESA_04", "key_004"),
        assistente_nome="Roberto Silva",
        logo_path="static/logos/empresa_04.png",
        rate_limit="80/hour",
    ),
    "empresa_05": EmpresaConfig(
        id="empresa_05",
        nome="Escritório Lima Contábil",
        db_path="db/empresa_05_sessions.db",
        ai_model="llama-3.1-8b-instant",
        ai_temperature=0.4,
        max_tokens=1200,
        api_key=os.getenv("API_KEY_EMPRESA_05", "key_005"),
        assistente_nome="Ana Paula",
        logo_path="static/logos/empresa_05.png",
        rate_limit="60/hour",
    ),
    "empresa_06": EmpresaConfig(
        id="empresa_06",
        nome="Assessoria Costa",
        db_path="db/empresa_06_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1500,
        api_key=os.getenv("API_KEY_EMPRESA_06", "key_006"),
        assistente_nome="Carlos Eduardo",
        logo_path="static/logos/empresa_06.png",
        rate_limit="100/hour",
    ),
    "empresa_07": EmpresaConfig(
        id="empresa_07",
        nome="RH Total Consultoria",
        db_path="db/empresa_07_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1800,
        api_key=os.getenv("API_KEY_EMPRESA_07", "key_007"),
        assistente_nome="Fernanda Alves",
        logo_path="static/logos/empresa_07.png",
        rate_limit="150/hour",
    ),
    "empresa_08": EmpresaConfig(
        id="empresa_08",
        nome="Contábil Express",
        db_path="db/empresa_08_sessions.db",
        ai_model="llama-3.1-8b-instant",
        ai_temperature=0.5,
        max_tokens=1000,
        api_key=os.getenv("API_KEY_EMPRESA_08", "key_008"),
        assistente_nome="Marcos Santos",
        logo_path="static/logos/empresa_08.png",
        rate_limit="40/hour",
    ),
    "empresa_09": EmpresaConfig(
        id="empresa_09",
        nome="Tributos & Cia",
        db_path="db/empresa_09_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.2,
        max_tokens=1600,
        api_key=os.getenv("API_KEY_EMPRESA_09", "key_009"),
        assistente_nome="Julia Martins",
        logo_path="static/logos/empresa_09.png",
        rate_limit="120/hour",
    ),
    "empresa_10": EmpresaConfig(
        id="empresa_10",
        nome="Gestão Contábil Moderna",
        db_path="db/empresa_10_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1500,
        api_key=os.getenv("API_KEY_EMPRESA_10", "key_010"),
        assistente_nome="Pedro Henrique",
        logo_path="static/logos/empresa_10.png",
        rate_limit="90/hour",
    ),
    "empresa_11": EmpresaConfig(
        id="empresa_11",
        nome="Auditoria Plus",
        db_path="db/empresa_11_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.25,
        max_tokens=2000,
        api_key=os.getenv("API_KEY_EMPRESA_11", "key_011"),
        assistente_nome="Beatriz Rocha",
        logo_path="static/logos/empresa_11.png",
        rate_limit="180/hour",
    ),
    "empresa_12": EmpresaConfig(
        id="empresa_12",
        nome="Folha de Pagamento Pro",
        db_path="db/empresa_12_sessions.db",
        ai_model="llama-3.1-8b-instant",
        ai_temperature=0.4,
        max_tokens=1200,
        api_key=os.getenv("API_KEY_EMPRESA_12", "key_012"),
        assistente_nome="Ricardo Mendes",
        logo_path="static/logos/empresa_12.png",
        rate_limit="70/hour",
    ),
    "empresa_13": EmpresaConfig(
        id="empresa_13",
        nome="Assessoria Empresarial",
        db_path="db/empresa_13_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.3,
        max_tokens=1500,
        api_key=os.getenv("API_KEY_EMPRESA_13", "key_013"),
        assistente_nome="Camila Ferreira",
        logo_path="static/logos/empresa_13.png",
        rate_limit="110/hour",
    ),
    "empresa_14": EmpresaConfig(
        id="empresa_14",
        nome="Contábil Digital",
        db_path="db/empresa_14_sessions.db",
        ai_model="llama-3.1-8b-instant",
        ai_temperature=0.5,
        max_tokens=1000,
        api_key=os.getenv("API_KEY_EMPRESA_14", "key_014"),
        assistente_nome="Lucas Oliveira",
        logo_path="static/logos/empresa_14.png",
        rate_limit="50/hour",
    ),
    "empresa_15": EmpresaConfig(
        id="empresa_15",
        nome="Planejamento Fiscal Avançado",
        db_path="db/empresa_15_sessions.db",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.2,
        max_tokens=2000,
        api_key=os.getenv("API_KEY_EMPRESA_15", "key_015"),
        assistente_nome="Mariana Costa",
        logo_path="static/logos/empresa_15.png",
        rate_limit="200/hour",
    ),
}


def get_empresa_config(empresa_id: str) -> EmpresaConfig:
    """Retorna configuração da empresa"""
    if empresa_id not in EMPRESAS:
        raise ValueError(f"Empresa '{empresa_id}' não encontrada")
    return EMPRESAS[empresa_id]


def validate_api_key(empresa_id: str, api_key: str) -> bool:
    """Valida API key da empresa"""
    if empresa_id not in EMPRESAS:
        return False
    return EMPRESAS[empresa_id].api_key == api_key


def listar_empresas() -> Dict[str, dict]:
    """Lista todas as empresas cadastradas"""
    return {
        empresa_id: {
            "nome": config.nome,
            "assistente": config.assistente_nome,
            "rate_limit": config.rate_limit,
        }
        for empresa_id, config in EMPRESAS.items()
    }
