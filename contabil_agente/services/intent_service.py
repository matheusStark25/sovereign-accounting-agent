import logging
import re
import unicodedata
from typing import Any, Dict

logger = logging.getLogger(__name__)


def normalizar_texto_avancado(texto: str) -> str:
    """Normalização avançada com correção de termos técnicos"""
    if not texto:
        return ""

    # Normalização Unicode
    s = unicodedata.normalize("NFKC", texto).strip()

    # Dicionário de correções técnicas
    correcoes = {
        "recisao": "rescisão",
        "ferias": "férias",
        "jao": "joão",
        "funcinario": "funcionário",
        "calculo": "cálculo",
        "contabil": "contábil",
        "imposto": "imposto",
        "salario": "salário",
        "prolabore": "pró-labore",
        "encargo": "encargo",
        "beneficio": "benefício",
        "tributo": "tributo",
        "fgts": "FGTS",
        "inss": "INSS",
        "irp": "IRP",
        "csll": "CSLL",
        "pis": "PIS",
        "cofins": "COFINS",
        "icms": "ICMS",
        "iss": "ISS",
        "mei": "MEI",
        "me": "ME",
        "eireli": "EIRELI",
        "ltda": "LTDA",
        "simples": "Simples Nacional",
        "presumido": "Lucro Presumido",
    }

    palavras = s.split()
    palavras_corrigidas = []

    for palavra in palavras:
        lower_palavra = palavra.lower()
        if lower_palavra in correcoes:
            corr = correcoes[lower_palavra]
            if palavra[0].isupper():
                corr = corr[0].upper() + corr[1:]
            palavras_corrigidas.append(corr)
        else:
            palavras_corrigidas.append(palavra)

    return " ".join(palavras_corrigidas)


def detectar_perfil_usuario(mensagem: str, historico: list = None) -> str:
    """Detecta automaticamente o perfil do usuário baseado em análise de linguagem"""
    score_idoso = 0
    score_rural = 0
    score_profissional = 0

    msg_lower = mensagem.lower()

    termos_idoso = [
        "aposentadoria",
        "aposentado",
        "pensão",
        "inss",
        "previdência",
        "benefício",
        "idoso",
        "terceira idade",
        "renda fixa",
        "poupança",
    ]
    score_idoso += sum(3 for termo in termos_idoso if termo in msg_lower)

    erros_tipicos = len(
        re.findall(
            r"(\b\w*([a-z])\2{2,}\w*\b)|([qwrtypsdfghjklçzxcvbnm]{4,})", msg_lower
        )
    )
    if erros_tipicos > 2:
        score_idoso += 4

    if sum(1 for c in mensagem if c.isupper()) > len(mensagem) * 0.5:
        score_idoso += 3

    termos_rural = [
        "roça",
        "fazenda",
        "sítio",
        "plantação",
        "colheita",
        "gado",
        "produção rural",
        "agricultura",
        "pecuária",
        "terra",
        "rural",
        "trator",
        "lavoura",
        "safra",
        "ITR",
    ]
    score_rural += sum(4 for termo in termos_rural if termo in msg_lower)

    palavras_simples = ["como", "fazer", "preciso", "onde", "quando", "ajuda", "me"]
    if sum(1 for p in palavras_simples if p in msg_lower) >= 3:
        score_rural += 2

    termos_tecnicos = ["compliance", "due diligence", "benchmark", "stakeholder", "ROI"]
    if not any(termo in msg_lower for termo in termos_tecnicos):
        score_rural += 1

    termos_profissionais = [
        "lucro presumido",
        "simples nacional",
        "regime tributário",
        "compliance",
        "due diligence",
        "margem ebitda",
        "DRE",
        "balanço",
        "análise financeira",
        "fluxo de caixa",
        "margem líquida",
    ]
    score_profissional += sum(4 for termo in termos_profissionais if termo in msg_lower)

    if len(mensagem.split()) > 20 and mensagem.count(",") > 2:
        score_profissional += 3

    if mensagem.count(".") > 0 and mensagem.count("?") <= 2:
        score_profissional += 2

    if historico and len(historico) > 5:
        score_profissional += 2

    scores = {
        "idoso": score_idoso,
        "rural": score_rural,
        "profissional": score_profissional,
    }
    perfil_detectado = (
        max(scores, key=scores.get) if max(scores.values()) > 0 else "profissional"
    )

    logger.info(f"Perfil detectado: {perfil_detectado} | Scores: {scores}")
    return perfil_detectado


def extrair_contexto_negocio(mensagem: str) -> Dict[str, Any]:
    """Extrai automaticamente contexto de negócio da mensagem"""
    contexto: Dict[str, Any] = {
        "tipo_empresa": None,
        "regime_tributario": None,
        "funcionarios": None,
        "faturamento": None,
        "localidade": None,
    }

    if re.search(
        r"simples\s*nacional|anexo\s+[iI]+[iI]*|simples", mensagem, re.IGNORECASE
    ):
        contexto["regime_tributario"] = "simples_nacional"
    elif re.search(r"presumido|lucro\s+presumido", mensagem, re.IGNORECASE):
        contexto["regime_tributario"] = "lucro_presumido"
    elif re.search(r"real|lucro\s+real", mensagem, re.IGNORECASE):
        contexto["regime_tributario"] = "lucro_real"

    match = re.search(
        r"(\d+)\s*(funcion[áa]rio|colaborador|empregado)", mensagem, re.IGNORECASE
    )
    if match:
        try:
            contexto["funcionarios"] = int(match.group(1))
        except Exception:
            pass

    match = re.search(
        r"faturamento\s*(de\s*)?R?\$?\s*(\d+[.,]?\d*)", mensagem, re.IGNORECASE
    )
    if match:
        try:
            contexto["faturamento"] = float(
                match.group(2).replace(".", "").replace(",", ".")
            )
        except Exception:
            pass

    match = re.search(
        r"(sp|são paulo|rj|rio|mg|minas|pr|paraná|rs|rio grande)",
        mensagem,
        re.IGNORECASE,
    )
    if match:
        contexto["localidade"] = match.group(1).upper()

    return contexto
