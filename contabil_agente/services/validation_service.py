"""
Serviço de Validação e Escalação Inteligente
Detecta automaticamente casos que precisam de validação CRC
"""

import logging
import re
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class ValidationService:
    """
    Identifica casos críticos que exigem validação do contador

    95% dos casos: IA resolve sozinha
    5% críticos: Escala para validação CRC
    """

    # Palavras-chave que indicam casos críticos
    CRITICAL_KEYWORDS = {
        "judicial": [
            "processo judicial",
            "ação trabalhista",
            "ação judicial",
            "execução fiscal",
            "mandado de segurança",
            "reclamatória trabalhista",
            "vara do trabalho",
            "justiça do trabalho",
            "advogado",
            "processo em andamento",
        ],
        "fiscalizacao": [
            "fiscalização",
            "receita federal",
            "auditor fiscal",
            "auto de infração",
            "intimação fiscal",
            "malha fina",
            "notificação receita",
            "SEFAZ",
            "fiscalização trabalhista",
        ],
        "reestruturacao": [
            "fusão",
            "cisão",
            "incorporação",
            "M&A",
            "aquisição",
            "compra de empresa",
            "venda de empresa",
            "mudança de controle",
            "alteração societária complexa",
        ],
        "recuperacao": [
            "recuperação judicial",
            "falência",
            "concordata",
            "insolvência",
            "pedido de falência",
        ],
        "parecer_tecnico": [
            "parecer técnico",
            "due diligence",
            "IPO",
            "financiamento bancário",
            "empréstimo acima",
            "investidor",
            "valuation",
            "auditoria externa",
        ],
    }

    @classmethod
    def requires_crc_validation(
        cls, message: str, response: str = ""
    ) -> Tuple[bool, str, str]:
        """
        Analisa se o caso requer validação CRC

        Args:
            message: Mensagem do usuário
            response: Resposta da IA (opcional)

        Returns:
            (requer_validacao, categoria, motivo)
        """
        text_combined = f"{message} {response}".lower()

        # Verifica marcador explícito
        if "[REQUER_VALIDACAO_CRC]" in response:
            return True, "explicito", "IA sinalizou necessidade de validação"

        # Detecta categorias críticas
        for categoria, keywords in cls.CRITICAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_combined:
                    motivo = cls._get_validation_reason(categoria)
                    return True, categoria, motivo

        # Detecta valores altos em operações
        if cls._has_high_value_operation(text_combined):
            return True, "alto_valor", "Operação de alto valor requer validação"

        return False, "", ""

    @classmethod
    def _get_validation_reason(cls, categoria: str) -> str:
        """Retorna motivo detalhado da validação"""
        reasons = {
            "judicial": "Caso envolve processo judicial - requer assinatura CRC",
            "fiscalizacao": "Fiscalização ativa - resposta exige contador responsável",
            "reestruturacao": "Reestruturação societária complexa - validação CRC obrigatória",
            "recuperacao": "Recuperação judicial/falência - especialização necessária",
            "parecer_tecnico": "Parecer técnico formal - assinatura CRC exigida",
        }
        return reasons.get(categoria, "Caso crítico identificado")

    @classmethod
    def _has_high_value_operation(cls, text: str) -> bool:
        """Detecta operações de alto valor que precisam validação"""
        # Padrões de valores altos (numéricos e abreviações)
        # 1) Valores numéricos com unidade (ex: '1000 mil', '0,5 mi', '1 milhão')
        numeric_unit_pattern = re.compile(
            r"(\d+[\d\.,]*)\s*(mil|milh[ãa]o|milh[oõ]es|milh[oõ]es|milhões|mi)\b",
            re.IGNORECASE,
        )

        # 2) Valores por extenso seguidos pela unidade (ex: 'quinhentos mil')
        words_unit_pattern = re.compile(
            r"([a-záéíóúãõç\s\-]+?)\s+(mil|milh[ãa]o|milh[oõ]es|milhões|mi)\b",
            re.IGNORECASE,
        )

        # 3) 'meio milhão' e variações
        meio_milhao_pattern = re.compile(r"\bmeio\s+milh[ãa]o\b", re.IGNORECASE)

        # Checa números com unidade
        for m in numeric_unit_pattern.finditer(text):
            num_str, unit = m.group(1), m.group(2)
            try:
                # Normaliza número (substitui '.' milhares e ',' decimais)
                normalized = num_str.replace(".", "").replace(",", ".")
                value = float(normalized)
            except ValueError:
                continue

            unit = unit.lower()
            if "mi" in unit or "milh" in unit:
                value *= 1_000_000
            elif "mil" == unit:
                value *= 1_000

            if value >= 500_000:
                return True

        # Checa expressões por extenso (palavras) seguidas de unidade
        def words_to_number(words: str) -> float:
            # Mapeamento simples de palavras para números (suporta até centena)
            mapping = {
                "zero": 0,
                "um": 1,
                "uma": 1,
                "dois": 2,
                "duas": 2,
                "três": 3,
                "tres": 3,
                "quatro": 4,
                "cinco": 5,
                "seis": 6,
                "sete": 7,
                "oito": 8,
                "nove": 9,
                "dez": 10,
                "onze": 11,
                "doze": 12,
                "treze": 13,
                "catorze": 14,
                "quatorze": 14,
                "quinze": 15,
                "dezesseis": 16,
                "dezassete": 17,
                "dezoito": 18,
                "dezenove": 19,
                "vinte": 20,
                "trinta": 30,
                "quarenta": 40,
                "cinquenta": 50,
                "sessenta": 60,
                "setenta": 70,
                "oitenta": 80,
                "noventa": 90,
                "cem": 100,
                "cento": 100,
                "duzentos": 200,
                "trezentos": 300,
                "quatrocentos": 400,
                "quinhentos": 500,
                "seiscentos": 600,
                "setecentos": 700,
                "oitocentos": 800,
                "novecentos": 900,
                "meio": 0.5,
            }

            total = 0.0
            parts = re.split(r"[\s-]+(?:e\s+)?", words.strip())
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if p in mapping:
                    total += mapping[p]
                else:
                    # tenta extrair dígitos dentro da palavra (caso '500')
                    digits = re.findall(r"\d+", p)
                    if digits:
                        try:
                            total += float(digits[0])
                        except ValueError:
                            continue

            return total

        for m in words_unit_pattern.finditer(text):
            words, unit = m.group(1), m.group(2)
            unit = unit.lower()
            num = words_to_number(words.lower())

            # Se não conseguimos converter, continue (não escalar por extenso ambíguo)
            if num == 0:
                # porém 'meio' já tratado abaixo; se não há número, ignoramos
                continue

            if unit.startswith("milh") or unit == "mi":
                value = num * 1_000_000
            elif unit == "mil":
                value = num * 1_000
            else:
                value = num

            if value >= 500_000:
                return True

        # 'meio milhão' explícito
        if meio_milhao_pattern.search(text):
            return True

        # Mantém verificação antiga simples (ex: R$ formatado)
        r_real_pattern = re.compile(r"R\$\s*[\d\.]+,\d{2}")
        if r_real_pattern.search(text):
            # tenta extrair número formatado
            num_match = re.search(r"R\$\s*([\d\.]+,\d{2})", text)
            if num_match:
                raw = num_match.group(1)
                try:
                    value = float(raw.replace(".", "").replace(",", "."))
                    if value >= 500_000:
                        return True
                except ValueError:
                    pass

        return False

    @classmethod
    def get_validation_message(cls, categoria: str, motivo: str) -> str:
        """Retorna mensagem adequada de escalação"""
        messages = {
            "judicial": (
                "⚖️ Como esse caso envolve processo judicial, vou encaminhar para "
                "o Pro escritório(CRC responsável) avaliar junto com nosso jurídico."
            ),
            "fiscalizacao": (
                "🔍 Fiscalização exige assinatura do contador responsável. "
                "Vou preparar tudo e o Pro escritório assina a resposta oficial."
            ),
            "reestruturacao": (
                "🏢 Operação dessa magnitude precisa de análise detalhada. "
                "Vou agendar uma reunião com você e o Pro escritório."
            ),
            "recuperacao": (
                "⚠️ Recuperação judicial exige contador especializado. "
                "Vou acionar nossa equipe de reestruturação empresarial."
            ),
            "parecer_tecnico": (
                "📋 Parecer técnico precisa assinatura CRC. "
                "Preparo os números e o Pro escritório faz a validação final."
            ),
            "alto_valor": (
                "💰 Por envolver valor significativo, vou validar com "
                "o Pro escritório antes de finalizar."
            ),
            "explicito": ("📢 Vou encaminhar para validação do contador responsável."),
        }

        return messages.get(
            categoria, "📋 Vou validar esse caso com o contador responsável."
        )

    @classmethod
    def analyze_confidence(cls, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analisa nível de confiança da IA em resolver o caso

        Returns:
            {
                "confidence": "high" | "medium" | "low",
                "should_escalate": bool,
                "reason": str
            }
        """
        message = context.get("message", "")
        response = context.get("response", "")

        requires_validation, categoria, motivo = cls.requires_crc_validation(
            message, response
        )

        if requires_validation:
            return {
                "confidence": "low",
                "should_escalate": True,
                "reason": motivo,
                "category": categoria,
                "validation_message": cls.get_validation_message(categoria, motivo),
            }

        # Alta confiança em casos rotineiros
        return {
            "confidence": "high",
            "should_escalate": False,
            "reason": "Caso rotineiro - dentro da expertise",
            "category": "routine",
        }


# Singleton global
validation_service = ValidationService()


def check_validation_needed(message: str, response: str = "") -> Dict[str, Any]:
    """Helper function para verificação rápida"""
    requires, cat, reason = validation_service.requires_crc_validation(
        message, response
    )

    if requires:
        return {
            "requires_validation": True,
            "category": cat,
            "reason": reason,
            "message": validation_service.get_validation_message(cat, reason),
        }

    return {"requires_validation": False}
