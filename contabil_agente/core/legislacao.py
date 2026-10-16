"""
Base de conhecimento - legislação trabalhista e fiscal.

Valores monetários (salário mínimo, teto e faixas do INSS, tabela do IRRF) NÃO ficam aqui:
vêm de ``contabil_agente.calc`` (``calc/data/tabelas.json``), a fonte única. O texto abaixo é
referência qualitativa; prazos e regras mudam, então confirme sempre na fonte oficial.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from contabil_agente.calc import calcular_inss as _calcular_inss
from contabil_agente.calc import calcular_irrf_mensal as _calcular_irrf
from contabil_agente.calc.tables import tabela_inss, tabela_irrf


def _competencia(competencia: Optional[date]) -> date:
    base = competencia or date.today()
    return date(base.year, base.month, 1)


class LegislacaoBrasileira:
    """Base de conhecimento legislativo."""

    # ==================== VALORES (via motor de cálculo) ====================

    @staticmethod
    def salario_minimo(competencia: Optional[date] = None) -> Decimal:
        return tabela_inss(_competencia(competencia)).salario_minimo

    @staticmethod
    def teto_inss(competencia: Optional[date] = None) -> Decimal:
        return tabela_inss(_competencia(competencia)).teto

    @staticmethod
    def tabela_inss(competencia: Optional[date] = None) -> List[Dict[str, Decimal]]:
        return [{"ate": f.ate, "aliquota": f.aliquota} for f in tabela_inss(_competencia(competencia)).faixas]

    @staticmethod
    def tabela_irrf(competencia: Optional[date] = None) -> List[Dict[str, Optional[Decimal]]]:
        return [
            {"ate": f.ate, "aliquota": f.aliquota, "deducao": f.deducao}
            for f in tabela_irrf(_competencia(competencia)).faixas
        ]

    @staticmethod
    def deducao_dependente_irrf(competencia: Optional[date] = None) -> Decimal:
        return tabela_irrf(_competencia(competencia)).deducao_dependente

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
        "limite_anual": Decimal("81000.00"),  # R$ 81 mil por ano
        "contribuicao_inss": "5% do salário mínimo; some R$ 1,00 de ICMS (comércio/indústria) e/ou R$ 5,00 de ISS (serviços)",
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
        "FGTS": "até dia 20 do mês seguinte, pelo FGTS Digital (confira o calendário oficial)",
        "DAS_Simples": "até dia 20 do mês seguinte",
        "DCTF_Web": "15º dia útil do mês seguinte",
        "EFD_Rein": "dia 15 do mês seguinte",
        "DIRF": "extinta: a última (ano-calendário 2024) foi entregue em fevereiro de 2025; desde então a informação vai pelo eSocial e pela EFD-Reinf",
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
    def calcular_inss(cls, salario: Decimal, competencia: Optional[date] = None) -> Decimal:
        """INSS do empregado (motor ``calc``); levanta erro se a competência não tiver tabela."""
        return _calcular_inss(salario, _competencia(competencia)).valor

    @classmethod
    def calcular_irrf(
        cls, rendimentos: Decimal, dependentes: int = 0, competencia: Optional[date] = None
    ) -> Decimal:
        """IRRF mensal sobre o rendimento tributável bruto (calcula o INSS e aplica a redução da Lei 15.270/2025)."""
        comp = _competencia(competencia)
        inss = _calcular_inss(rendimentos, comp).valor
        return _calcular_irrf(rendimentos, comp, inss=inss, dependentes=dependentes).valor

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
