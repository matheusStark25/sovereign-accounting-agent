"""
Base de Conhecimento - Legislação Trabalhista e Fiscal 2026
Referências atualizadas para consulta rápida pela IA
"""

from decimal import Decimal
from typing import Any, Dict, List


class LegislacaoBrasileira:
    """Base de conhecimento legislativo atualizada"""

    # ==================== VALORES 2026 ====================
    SALARIO_MINIMO_2026 = Decimal("1518.00")
    TETO_INSS_2026 = Decimal("8157.41")

    # Tabela INSS progressiva 2026
    TABELA_INSS_2026 = [
        {"ate": Decimal("1518.00"), "aliquota": Decimal("0.075")},
        {"ate": Decimal("2793.88"), "aliquota": Decimal("0.09")},
        {"ate": Decimal("4190.83"), "aliquota": Decimal("0.12")},
        {"ate": Decimal("8157.41"), "aliquota": Decimal("0.14")},
    ]

    # Tabela IRRF mensal 2026
    TABELA_IRRF_2026 = [
        {
            "ate": Decimal("2259.20"),
            "aliquota": Decimal("0"),
            "deducao": Decimal("0"),
        },
        {
            "ate": Decimal("2826.65"),
            "aliquota": Decimal("0.075"),
            "deducao": Decimal("169.44"),
        },
        {
            "ate": Decimal("3751.05"),
            "aliquota": Decimal("0.15"),
            "deducao": Decimal("381.44"),
        },
        {
            "ate": Decimal("4664.68"),
            "aliquota": Decimal("0.225"),
            "deducao": Decimal("662.77"),
        },
        {
            "ate": Decimal("999999.99"),
            "aliquota": Decimal("0.275"),
            "deducao": Decimal("896.00"),
        },
    ]

    DEDUCAO_DEPENDENTE_IRRF = Decimal("189.59")

    # ==================== CLT - CASOS ESPECIAIS ====================

    ESTABILIDADES = {
        "gestante": {
            "periodo": "confirmação gravidez até 5 meses após parto",
            "base_legal": "Art. 10, II, 'b', ADCT CF/88",
            "observacao": "Demissão nula, exige reintegração ou indenização",
        },
        "acidente_trabalho": {
            "periodo": "12 meses após alta médica",
            "base_legal": "Art. 118, Lei 8.213/91",
            "observacao": "Mesmo acidente de trajeto garante estabilidade",
        },
        "dirigente_sindical": {
            "periodo": "registro candidatura até 1 ano após fim mandato",
            "base_legal": "Art. 543, §3º, CLT",
            "observacao": "7 dirigentes sindicais por entidade sindical",
        },
        "cipeiro": {
            "periodo": "registro candidatura até 1 ano após fim mandato",
            "base_legal": "Art. 10, II, 'a', ADCT CF/88",
            "observacao": "Titulares e suplentes têm estabilidade",
        },
        "pre_aposentadoria": {
            "periodo": "2 anos antes de completar requisitos aposentadoria",
            "base_legal": "Convenção Coletiva (quando prevista)",
            "observacao": "NÃO é CLT, depende de convenção/acordo coletivo",
        },
    }

    TIPOS_AFASTAMENTO = {
        "doenca_comum": {
            "periodo_empresa": "15 dias",
            "apos": "INSS assume (auxílio-doença)",
            "base_legal": "Art. 60, Lei 8.213/91",
        },
        "acidente_trabalho": {
            "periodo_empresa": "15 dias",
            "apos": "INSS assume (auxílio-doença acidentário)",
            "estabilidade": "12 meses após alta",
            "base_legal": "Art. 118, Lei 8.213/91",
        },
        "licenca_maternidade": {
            "periodo": "120 dias (pode ser 180 dias Empresa Cidadã)",
            "estabilidade": "até 5 meses após parto",
            "base_legal": "Art. 392, CLT + Lei 11.770/08",
        },
        "licenca_paternidade": {
            "periodo": "5 dias (pode ser 20 dias Empresa Cidadã)",
            "base_legal": "Art. 473, CLT + Lei 11.770/08",
        },
    }

    # ==================== REGIMES TRIBUTÁRIOS ====================

    SIMPLES_NACIONAL = {
        "limite_anual": Decimal("4800000.00"),  # R$ 4,8mi
        "anexos": {
            "I": "Comércio",
            "II": "Indústria",
            "III": "Serviços (locação, cessão mão de obra)",
            "IV": "Serviços (limpeza, vigilância, obras)",
            "V": "Serviços (advocacia, contabilidade, TI)",
        },
        "restricoes": [
            "Não pode ter sócio PJ",
            "Não pode ter débito INSS/Receita",
            "Não pode ser banco/financeira",
        ],
    }

    LUCRO_PRESUMIDO = {
        "limite_anual": Decimal("78000000.00"),  # R$ 78mi
        "percentuais_presuncao": {
            "comercio": Decimal("0.08"),  # 8%
            "industria": Decimal("0.08"),
            "servicos_geral": Decimal("0.32"),  # 32%
            "transporte_carga": Decimal("0.08"),
            "transporte_passageiros": Decimal("0.16"),
        },
        "vantagens": ["Simplicidade", "Menor carga se margem > presunção"],
        "desvantagens": ["Tributa mesmo com prejuízo"],
    }

    LUCRO_REAL = {
        "obrigatorio_se": [
            "Faturamento > R$ 78mi/ano",
            "Atividade financeira",
            "Lucros do exterior",
        ],
        "vantagens": ["Compensa prejuízos", "Incentivos fiscais"],
        "desvantagens": ["Complexidade contábil", "Custo compliance alto"],
    }

    MICROEMPREENDEDOR_INDIVIDUAL = {
        "limite_anual": Decimal("81000.00"),  # R$ 81mi
        "contribuicao_mensal": Decimal("71.60"),  # 2026 (5% salário mínimo + R$ 1)
        "restricoes": [
            "Apenas 1 empregado (salário mínimo ou piso categoria)",
            "Atividades permitidas (lista CGSIM)",
            "Não pode ter sócio",
            "Não pode ser sócio/administrador outra empresa",
        ],
    }

    # ==================== OBRIGAÇÕES ACESSÓRIAS ====================

    PRAZOS_OBRIGACOES = {
        "eSocial_folha": "até dia 15 do mês seguinte",
        "GPS_INSS": "até dia 20 do mês seguinte",
        "FGTS": "até dia 7 do mês seguinte",
        "DAS_Simples": "até dia 20 do mês seguinte",
        "DCTF_Web": "15º dia útil do mês seguinte",
        "EFD_Rein": "dia 15 do mês seguinte",
        "DIRF": "último dia útil de fevereiro (anual)",
        "IRPF": "até 31 de maio (anual)",
        "DEFIS_MEI": "até 31 de maio (anual)",
    }

    # ==================== VERBAS RESCISÓRIAS ====================

    VERBAS_RESCISAO = {
        "demissao_sem_justa_causa": [
            "Saldo de salário",
            "Aviso prévio (trabalhado ou indenizado)",
            "13º proporcional",
            "Férias vencidas + 1/3",
            "Férias proporcionais + 1/3",
            "Multa 40% FGTS",
            "Saque FGTS",
            "Seguro-desemprego (se requisitos)",
        ],
        "demissao_justa_causa": [
            "Apenas saldo de salário",
            "Férias vencidas + 1/3 (se houver)",
        ],
        "pedido_demissao": [
            "Saldo de salário",
            "13º proporcional",
            "Férias vencidas + 1/3",
            "Férias proporcionais + 1/3",
        ],
        "acordo_mutuo": [
            "Saldo de salário",
            "Metade aviso prévio indenizado",
            "13º proporcional",
            "Férias vencidas + 1/3",
            "Férias proporcionais + 1/3",
            "Multa 20% FGTS (metade)",
            "Saque 80% FGTS",
            "SEM seguro-desemprego",
        ],
    }

    # ==================== MÉTODOS AUXILIARES ====================

    @classmethod
    def calcular_inss(cls, salario: Decimal) -> Decimal:
        """Calcula INSS progressivo 2026"""
        if salario > cls.TETO_INSS_2026:
            salario = cls.TETO_INSS_2026

        inss = Decimal("0")
        base_anterior = Decimal("0")

        for faixa in cls.TABELA_INSS_2026:
            teto_faixa = faixa["ate"]
            aliquota = faixa["aliquota"]

            if salario > teto_faixa:
                base_faixa = teto_faixa - base_anterior
                inss += base_faixa * aliquota
                base_anterior = teto_faixa
            else:
                base_faixa = salario - base_anterior
                inss += base_faixa * aliquota
                break

        return inss.quantize(Decimal("0.01"))

    @classmethod
    def calcular_irrf(cls, base: Decimal, dependentes: int = 0) -> Decimal:
        """Calcula IRRF mensal 2026"""
        # Deduz dependentes
        base_calc = base - (cls.DEDUCAO_DEPENDENTE_IRRF * dependentes)

        if base_calc <= Decimal("0"):
            return Decimal("0")

        # Encontra faixa
        for faixa in cls.TABELA_IRRF_2026:
            if base_calc <= faixa["ate"]:
                irrf = (base_calc * faixa["aliquota"]) - faixa["deducao"]
                return max(Decimal("0"), irrf.quantize(Decimal("0.01")))

        return Decimal("0")

    @classmethod
    def get_info_estabilidade(cls, tipo: str) -> Dict[str, str]:
        """Retorna informações sobre estabilidade"""
        return cls.ESTABILIDADES.get(tipo.lower(), {})

    @classmethod
    def comparar_regimes(cls, faturamento_anual: Decimal) -> List[Dict[str, Any]]:
        """Sugere melhor regime tributário baseado no faturamento"""
        opcoes = []

        if faturamento_anual <= cls.MICROEMPREENDEDOR_INDIVIDUAL["limite_anual"]:
            opcoes.append(
                {
                    "regime": "MEI",
                    "viavel": True,
                    "observacao": "Mais econômico se atender requisitos",
                }
            )

        if faturamento_anual <= cls.SIMPLES_NACIONAL["limite_anual"]:
            opcoes.append(
                {
                    "regime": "Simples Nacional",
                    "viavel": True,
                    "observacao": "Analise anexo específico da atividade",
                }
            )

        if faturamento_anual <= cls.LUCRO_PRESUMIDO["limite_anual"]:
            opcoes.append(
                {
                    "regime": "Lucro Presumido",
                    "viavel": True,
                    "observacao": "Vantajoso se margem > percentual presunção",
                }
            )

        opcoes.append(
            {
                "regime": "Lucro Real",
                "viavel": True,
                "observacao": "Compensa prejuízos, mais complexo",
            }
        )

        return opcoes


# Singleton para acesso rápido
legislacao = LegislacaoBrasileira()
