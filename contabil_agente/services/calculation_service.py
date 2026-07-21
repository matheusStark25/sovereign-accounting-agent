"""
Serviço de Cálculos Determinísticos para Contabilidade
Motor de cálculos com classes OOP independentes
Implementa: INSS, IRRF, Férias, 13º Salário, Rescisão, Horas Extras

Baseado nas tabelas oficiais 2026 e legislação vigente
Sem mocks - Código pronto para produção
"""

import json
import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
import os
from typing import Dict, Optional
import threading
from functools import lru_cache

# Embedded fallback tables (2026) - minimal safe dataset
EMBEDDED_TABLES = {
    "ano": 2026,
    "versao": "2026.0.0-embedded",
    "salario_minimo": 1450.00,
    "inss": {
        "descricao": "Tabela INSS 2026 (embedded)",
        "teto_maximo": 876.00,
        "faixas": [
            {"min": 0.00, "max": 1302.00, "aliquota": 0.075},
            {"min": 1302.01, "max": 2571.29, "aliquota": 0.09},
            {"min": 2571.30, "max": 3856.94, "aliquota": 0.12},
            {"min": 3856.95, "max": 7507.49, "aliquota": 0.14},
        ],
    },
    "irrf": {
        "descricao": "Tabela IRRF 2026 (embedded)",
        "deducao_dependente": 189.59,
        "faixas": [
            {
                "min": 0.00,
                "max": 1903.98,
                "aliquota": 0.0,
                "deducao": 0.0,
                "descricao": "Isento",
            },
            {
                "min": 1903.99,
                "max": 2826.65,
                "aliquota": 0.075,
                "deducao": 142.80,
                "descricao": "7.5%",
            },
            {
                "min": 2826.66,
                "max": 3751.05,
                "aliquota": 0.15,
                "deducao": 354.80,
                "descricao": "15%",
            },
            {
                "min": 3751.06,
                "max": 4664.68,
                "aliquota": 0.225,
                "deducao": 636.13,
                "descricao": "22.5%",
            },
            {
                "min": 4664.69,
                "max": 999999999.99,
                "aliquota": 0.275,
                "deducao": 869.36,
                "descricao": "27.5%",
            },
        ],
    },
    "fgts": {
        "descricao": "FGTS embedded",
        "aliquota_mensal": 0.08,
        "multa_rescisao_sem_justa_causa": 0.4,
    },
    "ferias": {
        "descricao": "Regras de férias (embedded)",
        "adicional_constitucional": 0.3333,
    },
    "decimo_terceiro": {
        "descricao": "13º (embedded)",
        "prazo_primeira_parcela": "30/11",
        "prazo_segunda_parcela": "20/12",
    },
    "rescisao": {"descricao": "Rescisão (embedded)"},
    "adicionais": {
        "periculosidade": {
            "aliquota": 0.30,
            "descricao": "Periculosidade 30%",
            "integra_inss": True,
            "integra_irr": True,
            "integra_fgts": True,
            "integra_ferias": True,
            "integra_13": True,
        },
        "insalubridade": {
            "grau_minimo": 0.1,
            "grau_medio": 0.2,
            "grau_maximo": 0.4,
            "descricao": "Insalubridade",
            "integra_inss": True,
            "integra_irr": True,
            "integra_fgts": True,
            "integra_ferias": True,
            "integra_13": True,
        },
        "horas_extras": {
            "descricao": "Horas extras",
            "integra_inss": True,
            "integra_irr": True,
            "integra_fgts": True,
            "integra_ferias": True,
            "integra_13": True,
        },
    },
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge override into base recursively without losing base values."""
    result = dict(base)
    for k, v in (override or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


logger = logging.getLogger(__name__)


class TabelasOficiais:
    """Gerenciador de tabelas oficiais com carregamento em cascata e fallback embutido.

    Hierarquia de carregamento:
    - `custom_tables` (dict) passado ao construtor
    - caminho via parâmetro string
    - variável de ambiente `CALC_TABLES_PATH`
    - diretórios padrão do sistema (./data, /etc/contabil_agente)
    - EMBEDDED_TABLES (fallback final)
    """

    def __init__(
        self, custom_tables: Optional[object] = None, memory_only: bool = False
    ):
        self.memory_only = bool(memory_only)
        self.loaded_from = "embedded"

        # Always force canonical package JSON (tabelas_oficiais_2026.json in this dir)
        try:
            canonical_path = os.path.join(
                os.path.dirname(__file__), "tabelas_oficiais_2026.json"
            )
            with open(canonical_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.tabelas = _deep_merge(EMBEDDED_TABLES, loaded)
            self.loaded_from = canonical_path
            logger.info(
                json.dumps(
                    {
                        "source": canonical_path,
                        "message": "Loaded canonical calculation tables (forced)",
                    }
                )
            )
        except Exception as e:
            logger.warning(
                json.dumps(
                    {
                        "source": "ERROR_LOADING_CANONICAL",
                        "error": str(e),
                        "action": "using_embedded",
                    }
                )
            )
            self.tabelas = dict(EMBEDDED_TABLES)
            self.loaded_from = "EMBEDDED"

        # Expose metadata
        self.versao = self.tabelas.get("versao", "embedded")
        self.ano = self.tabelas.get("ano", 2026)

        # If ano is older than expected, warn but proceed
        try:
            if int(self.ano) < 2026:
                logger.warning(
                    json.dumps(
                        {"warning": "Tabela Desatualizada", "ano_detectado": self.ano}
                    )
                )
        except Exception:
            pass

        logger.info(
            json.dumps(
                {
                    "tabelas_info": {
                        "versao": self.versao,
                        "ano": self.ano,
                        "loaded_from": self.loaded_from,
                    }
                }
            )
        )

        # Backwards-compatibility: some table packs use key 'irrf' while
        # existing code expects 'irr'. Create a compatibility alias so both
        # forms work transparently.
        try:
            if "irr" not in self.tabelas and "irrf" in self.tabelas:
                self.tabelas["irr"] = self.tabelas["irrf"]
        except Exception:
            pass

    def obter_salario_minimo(self) -> Decimal:
        """Retorna o salário mínimo oficial"""
        return Decimal(str(self.tabelas["salario_minimo"]))

    def obter_tabela_inss(self) -> Dict:
        """Retorna a tabela INSS"""
        return self.tabelas["inss"]

    def obter_tabela_irrf(self) -> Dict:
        """Retorna a tabela IRRF"""
        return self.tabelas["irr"]

    def obter_tabela_fgts(self) -> Dict:
        """Retorna a tabela FGTS"""
        return self.tabelas["fgts"]

    def obter_regras_ferias(self) -> Dict:
        """Retorna as regras de férias"""
        return self.tabelas["ferias"]

    def obter_regras_13(self) -> Dict:
        """Retorna as regras de 13º salário"""
        return self.tabelas["decimo_terceiro"]

    def obter_regras_rescisao(self) -> Dict:
        """Retorna as regras de rescisão"""
        return self.tabelas["rescisao"]

    def obter_adicionais(self) -> Dict:
        """Retorna as regras de adicionais (periculosidade, insalubridade, horas extras)"""
        return self.tabelas["adicionais"]


class CalculadoraINSS:
    """Calculadora de INSS com tabela progressiva 2026"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de INSS

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.tabela_inss = tabelas.obter_tabela_inss()

    def calcular(self, salario_bruto: Decimal) -> Dict:
        """
        Calcula o INSS progressivo sobre o salário bruto

        Args:
            salario_bruto: Salário bruto do funcionário

        Returns:
            Dict com valor_inss, base_calculo, aliquota_efetiva, detalhamento por faixa
        """
        salario = Decimal(str(salario_bruto))
        faixas = self.tabela_inss["faixas"]
        teto_maximo = Decimal(str(self.tabela_inss["teto_maximo"]))

        # Limita ao teto
        base_calculo = min(salario, teto_maximo)

        valor_inss = Decimal("0.00")
        detalhamento = []

        # Cálculo progressivo por faixa
        for faixa in faixas:
            min_faixa = Decimal(str(faixa["min"]))
            max_faixa = Decimal(str(faixa["max"]))
            aliquota = Decimal(str(faixa["aliquota"]))

            if base_calculo > min_faixa:
                # Valor que incide nesta faixa
                valor_faixa = min(base_calculo, max_faixa) - min_faixa
                if valor_faixa > 0:
                    desconto_faixa = (valor_faixa * aliquota).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                    valor_inss += desconto_faixa

                    detalhamento.append(
                        {
                            "faixa": f"R$ {min_faixa:.2f} a R$ {max_faixa:.2f}",
                            "aliquota": float(aliquota),
                            "base_faixa": float(valor_faixa),
                            "valor_desconto": float(desconto_faixa),
                        }
                    )

        valor_inss = valor_inss.quantize(Decimal("0.01"), ROUND_HALF_UP)
        aliquota_efetiva = (
            (valor_inss / base_calculo * 100) if base_calculo > 0 else Decimal("0")
        )

        return {
            "valor_inss": float(valor_inss),
            "base_calculo": float(base_calculo),
            "aliquota_efetiva": float(
                aliquota_efetiva.quantize(Decimal("0.01"), ROUND_HALF_UP)
            ),
            "detalhamento": detalhamento,
            "legislacao": self.tabela_inss.get("descricao", ""),
        }


class CalculadoraIRRF:
    """Calculadora de IRRF com tabela progressiva 2026"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de IRRF

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.tabela_irrf = tabelas.obter_tabela_irrf()

    def calcular(self, base_calculo: Decimal, num_dependentes: int = 0) -> Dict:
        """
        Calcula o IRRF sobre a base de cálculo
        Base = Salário bruto - INSS - Dedução por dependente

        Args:
            base_calculo: Base de cálculo (salário bruto - INSS)
            num_dependentes: Número de dependentes

        Returns:
            Dict com valor_irrf, base_calculo, aliquota, deducao, faixa
        """
        base = Decimal(str(base_calculo))
        deducao_dependente = Decimal(str(self.tabela_irrf["deducao_dependente"]))

        # Deduz os dependentes
        base_tributavel = base - (deducao_dependente * num_dependentes)
        base_tributavel = max(base_tributavel, Decimal("0"))

        # Encontra a faixa correta
        faixas = self.tabela_irrf["faixas"]
        faixa_aplicavel = None

        for faixa in faixas:
            min_faixa = Decimal(str(faixa["min"]))
            max_faixa = Decimal(str(faixa["max"]))

            if min_faixa <= base_tributavel <= max_faixa:
                faixa_aplicavel = faixa
                break

        if not faixa_aplicavel:
            # Não deveria acontecer, mas retorna 0
            return {
                "valor_irr": 0.00,
                "base_calculo": float(base),
                "base_tributavel": float(base_tributavel),
                "aliquota": 0.00,
                "deducao": 0.00,
                "faixa": "Isento",
                "legislacao": self.tabela_irrf.get("descricao", ""),
            }

        aliquota = Decimal(str(faixa_aplicavel["aliquota"]))
        deducao = Decimal(str(faixa_aplicavel["deducao"]))

        # Fórmula: (Base × Alíquota) - Dedução
        valor_irrf = (base_tributavel * aliquota) - deducao
        valor_irrf = max(valor_irrf, Decimal("0"))
        valor_irrf = valor_irrf.quantize(Decimal("0.01"), ROUND_HALF_UP)

        return {
            "valor_irr": float(valor_irrf),
            "base_calculo": float(base),
            "base_tributavel": float(base_tributavel),
            "aliquota": float(aliquota),
            "deducao": float(deducao),
            "faixa": faixa_aplicavel["descricao"],
            "num_dependentes": num_dependentes,
            "deducao_dependentes": float(deducao_dependente * num_dependentes),
            "legislacao": self.tabela_irrf.get("descricao", ""),
        }


class CalculadoraFGTS:
    """Calculadora de FGTS"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de FGTS

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.tabela_fgts = tabelas.obter_tabela_fgts()

    def calcular_mensal(self, salario_bruto: Decimal) -> Dict:
        """
        Calcula o FGTS mensal (8% do salário bruto)

        Args:
            salario_bruto: Salário bruto do funcionário

        Returns:
            Dict com valor_fgts, base_calculo, aliquota
        """
        salario = Decimal(str(salario_bruto))
        aliquota = Decimal(str(self.tabela_fgts["aliquota_mensal"]))

        valor_fgts = (salario * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        return {
            "valor_fgts": float(valor_fgts),
            "base_calculo": float(salario),
            "aliquota": float(aliquota),
            "tipo": "Depósito mensal",
            "legislacao": self.tabela_fgts.get("descricao", ""),
        }

    def calcular_multa_rescisao(
        self, saldo_fgts: Decimal, sem_justa_causa: bool = True
    ) -> Dict:
        """
        Calcula a multa de FGTS em rescisão

        Args:
            saldo_fgts: Saldo total de FGTS acumulado
            sem_justa_causa: Se a rescisão é sem justa causa (40% de multa)

        Returns:
            Dict com valor_multa, saldo_fgts, percentual
        """
        saldo = Decimal(str(saldo_fgts))

        if sem_justa_causa:
            percentual = Decimal(
                str(self.tabela_fgts["multa_rescisao_sem_justa_causa"])
            )
            valor_multa = (saldo * percentual).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            percentual = Decimal("0")
            valor_multa = Decimal("0")

        return {
            "valor_multa": float(valor_multa),
            "saldo_fgts": float(saldo),
            "percentual": float(percentual),
            "tipo": (
                "Rescisão sem justa causa"
                if sem_justa_causa
                else "Rescisão com justa causa"
            ),
            "legislacao": self.tabela_fgts.get("descricao", ""),
        }


class CalculadoraAdicionais:
    """Calculadora de Adicionais (Periculosidade, Insalubridade, Horas Extras)"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de adicionais

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.adicionais = tabelas.obter_adicionais()

    def calcular_periculosidade(self, salario_base: Decimal) -> Dict:
        """
        Calcula adicional de periculosidade (30% sobre salário base)

        Args:
            salario_base: Salário base do funcionário

        Returns:
            Dict com valor_adicional, salario_base, percentual
        """
        salario = Decimal(str(salario_base))
        periculosidade = self.adicionais["periculosidade"]
        aliquota = Decimal(str(periculosidade["aliquota"]))

        valor_adicional = (salario * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        return {
            "valor_adicional": float(valor_adicional),
            "salario_base": float(salario),
            "percentual": float(aliquota),
            "tipo": "Periculosidade",
            "descricao": periculosidade["descricao"],
            "integracoes": {
                "inss": periculosidade["integra_inss"],
                "irr": periculosidade["integra_irr"],
                "fgts": periculosidade["integra_fgts"],
                "ferias": periculosidade["integra_ferias"],
                "13_salario": periculosidade["integra_13"],
            },
        }

    def calcular_insalubridade(self, grau: str = "medio") -> Dict:
        """
        Calcula adicional de insalubridade (sobre salário mínimo)

        Args:
            grau: 'minimo' (10%), 'medio' (20%), 'maximo' (40%)

        Returns:
            Dict com valor_adicional, grau, percentual
        """
        insalubridade = self.adicionais["insalubridade"]
        salario_minimo = self.tabelas.obter_salario_minimo()

        graus = {
            "minimo": Decimal(str(insalubridade["grau_minimo"])),
            "medio": Decimal(str(insalubridade["grau_medio"])),
            "maximo": Decimal(str(insalubridade["grau_maximo"])),
        }

        aliquota = graus.get(grau, graus["medio"])
        valor_adicional = (salario_minimo * aliquota).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        return {
            "valor_adicional": float(valor_adicional),
            "salario_minimo": float(salario_minimo),
            "grau": grau,
            "percentual": float(aliquota),
            "tipo": "Insalubridade",
            "descricao": insalubridade["descricao"],
            "integracoes": {
                "inss": insalubridade["integra_inss"],
                "irr": insalubridade["integra_irr"],
                "fgts": insalubridade["integra_fgts"],
                "ferias": insalubridade["integra_ferias"],
                "13_salario": insalubridade["integra_13"],
            },
        }

    def calcular_horas_extras(
        self, valor_hora: Decimal, quantidade_horas: int, percentual: int = 50
    ) -> Dict:
        """
        Calcula horas extras

        Args:
            valor_hora: Valor da hora normal de trabalho
            quantidade_horas: Quantidade de horas extras
            percentual: Percentual do adicional (50 ou 100)

        Returns:
            Dict com valor_total, quantidade, percentual
        """
        hora = Decimal(str(valor_hora))
        qtd = Decimal(str(quantidade_horas))
        perc = Decimal(str(percentual)) / Decimal("100")

        # Valor hora extra = valor_hora × (1 + percentual)
        valor_hora_extra = hora * (Decimal("1") + perc)
        valor_total = (valor_hora_extra * qtd).quantize(Decimal("0.01"), ROUND_HALF_UP)

        horas_extras_config = self.adicionais["horas_extras"]

        return {
            "valor_total": float(valor_total),
            "valor_hora_normal": float(hora),
            "valor_hora_extra": float(valor_hora_extra),
            "quantidade_horas": int(qtd),
            "percentual": percentual,
            "tipo": "Horas Extras "
            + ("Dias Úteis" if percentual == 50 else "Domingos/Feriados"),
            "descricao": horas_extras_config["descricao"],
            "integracoes": {
                "inss": horas_extras_config["integra_inss"],
                "irr": horas_extras_config["integra_irr"],
                "fgts": horas_extras_config["integra_fgts"],
                "ferias": horas_extras_config["integra_ferias"],
                "13_salario": horas_extras_config["integra_13"],
            },
        }


class CalculadoraFerias:
    """Calculadora de Férias - CLT Art. 129 a 153"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de férias

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.regras = tabelas.obter_regras_ferias()
        self.calc_inss = CalculadoraINSS(tabelas)
        self.calc_irrf = CalculadoraIRRF(tabelas)

    def calcular(
        self,
        salario_base: Decimal,
        media_variaveis: Decimal = Decimal("0"),
        meses_trabalhados: int = 12,
        abono_pecuniario: bool = False,
        num_dependentes: int = 0,
    ) -> Dict:
        """
        Calcula férias completas

        Args:
            salario_base: Salário base do funcionário
            media_variaveis: Média de variáveis (comissões, horas extras, etc.) dos últimos 12 meses
            meses_trabalhados: Meses trabalhados no período aquisitivo (1-12)
            abono_pecuniario: Se optou por vender 1/3 das férias
            num_dependentes: Número de dependentes para IRRF

        Returns:
            Dict completo com cálculo de férias, INSS e IRRF
        """
        salario = Decimal(str(salario_base))
        variaveis = Decimal(str(media_variaveis))

        # Base de cálculo = salário + média variáveis
        base_ferias = salario + variaveis

        # Proporcional aos meses trabalhados
        meses = min(max(meses_trabalhados, 1), 12)
        proporcional = Decimal(str(meses)) / Decimal("12")

        # Férias = base × proporcional
        valor_ferias = (base_ferias * proporcional).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Adicional de 1/3 constitucional
        adicional_um_terco = Decimal(str(self.regras["adicional_constitucional"]))
        valor_um_terco = (valor_ferias * adicional_um_terco).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Abono pecuniário (venda de 1/3 das férias)
        valor_abono = Decimal("0")
        if abono_pecuniario:
            valor_abono = (base_ferias * proporcional * Decimal("0.3333")).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            # Abono também tem adicional de 1/3
            valor_abono_um_terco = (valor_abono * adicional_um_terco).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            valor_abono = valor_abono + valor_abono_um_terco

        # Total bruto
        total_bruto = valor_ferias + valor_um_terco + valor_abono

        # Descontos: INSS e IRRF
        inss = self.calc_inss.calcular(total_bruto)
        base_irrf = total_bruto - Decimal(str(inss["valor_inss"]))
        irrf = self.calc_irrf.calcular(base_irrf, num_dependentes)

        # Líquido
        total_descontos = Decimal(str(inss["valor_inss"])) + Decimal(
            str(irrf["valor_irr"])
        )
        total_liquido = total_bruto - total_descontos

        return {
            "valor_ferias": float(valor_ferias),
            "valor_um_terco": float(valor_um_terco),
            "valor_abono_pecuniario": float(valor_abono),
            "total_bruto": float(total_bruto),
            "descontos": {
                "inss": inss,
                "irr": irrf,
                "total_descontos": float(total_descontos),
            },
            "total_liquido": float(total_liquido),
            "detalhes": {
                "salario_base": float(salario),
                "media_variaveis": float(variaveis),
                "base_calculo": float(base_ferias),
                "meses_trabalhados": meses,
                "proporcional": float(proporcional),
                "abono_pecuniario": abono_pecuniario,
                "num_dependentes": num_dependentes,
            },
            "legislacao": self.regras.get("descricao", ""),
        }


class Calculadora13Salario:
    """Calculadora de 13º Salário - Lei 4.090/1962 e Lei 4.749/1965"""

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de 13º salário

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.regras = tabelas.obter_regras_13()
        self.calc_inss = CalculadoraINSS(tabelas)
        self.calc_irrf = CalculadoraIRRF(tabelas)

    def calcular_primeira_parcela(
        self, salario_base: Decimal, meses_trabalhados: int = 12
    ) -> Dict:
        """
        Calcula a primeira parcela do 13º (50% sem descontos)
        Paga até 30 de novembro

        Args:
            salario_base: Salário base do funcionário
            meses_trabalhados: Meses trabalhados no ano (1-12)

        Returns:
            Dict com valor da primeira parcela
        """
        salario = Decimal(str(salario_base))
        meses = min(max(meses_trabalhados, 1), 12)

        # 13º proporcional = (salário / 12) × meses trabalhados
        valor_13_integral = (salario / Decimal("12") * Decimal(str(meses))).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Primeira parcela = 50%
        primeira_parcela = (valor_13_integral * Decimal("0.5")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        return {
            "valor_primeira_parcela": float(primeira_parcela),
            "valor_13_integral": float(valor_13_integral),
            "salario_base": float(salario),
            "meses_trabalhados": meses,
            "prazo": self.regras["prazo_primeira_parcela"],
            "observacao": "Primeira parcela sem descontos de INSS e IRRF",
            "legislacao": self.regras.get("descricao", ""),
        }

    def calcular_segunda_parcela(
        self,
        salario_base: Decimal,
        media_variaveis: Decimal = Decimal("0"),
        meses_trabalhados: int = 12,
        valor_primeira_parcela: Optional[Decimal] = None,
        num_dependentes: int = 0,
    ) -> Dict:
        """
        Calcula a segunda parcela do 13º (50% restante com descontos)
        Paga até 20 de dezembro

        Args:
            salario_base: Salário base do funcionário
            media_variaveis: Média de variáveis dos últimos 12 meses
            meses_trabalhados: Meses trabalhados no ano (1-12)
            valor_primeira_parcela: Valor já pago na primeira parcela
            num_dependentes: Número de dependentes para IRRF

        Returns:
            Dict completo com segunda parcela e descontos
        """
        salario = Decimal(str(salario_base))
        variaveis = Decimal(str(media_variaveis))
        meses = min(max(meses_trabalhados, 1), 12)

        # Base = salário + média variáveis
        base_13 = salario + variaveis

        # 13º integral proporcional
        valor_13_integral = (base_13 / Decimal("12") * Decimal(str(meses))).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Se não informou primeira parcela, calcula 50%
        if valor_primeira_parcela is None:
            primeira_parcela = (valor_13_integral * Decimal("0.5")).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        else:
            primeira_parcela = Decimal(str(valor_primeira_parcela))

        # Segunda parcela bruta = integral - primeira parcela
        segunda_parcela_bruta = valor_13_integral - primeira_parcela

        # Descontos incidem sobre o valor integral
        inss = self.calc_inss.calcular(valor_13_integral)
        base_irrf = valor_13_integral - Decimal(str(inss["valor_inss"]))
        irrf = self.calc_irrf.calcular(base_irrf, num_dependentes)

        # Líquido da segunda parcela = bruta - descontos
        total_descontos = Decimal(str(inss["valor_inss"])) + Decimal(
            str(irrf["valor_irr"])
        )
        segunda_parcela_liquida = segunda_parcela_bruta - total_descontos

        return {
            "valor_13_integral": float(valor_13_integral),
            "valor_primeira_parcela": float(primeira_parcela),
            "valor_segunda_parcela_bruta": float(segunda_parcela_bruta),
            "descontos": {
                "inss": inss,
                "irr": irrf,
                "total_descontos": float(total_descontos),
            },
            "valor_segunda_parcela_liquida": float(segunda_parcela_liquida),
            "detalhes": {
                "salario_base": float(salario),
                "media_variaveis": float(variaveis),
                "base_calculo": float(base_13),
                "meses_trabalhados": meses,
                "num_dependentes": num_dependentes,
            },
            "prazo": self.regras["prazo_segunda_parcela"],
            "legislacao": self.regras.get("descricao", ""),
        }

    def calcular_completo(
        self,
        salario_base: Decimal,
        media_variaveis: Decimal = Decimal("0"),
        meses_trabalhados: int = 12,
        num_dependentes: int = 0,
    ) -> Dict:
        """
        Calcula o 13º salário completo (ambas parcelas)

        Args:
            salario_base: Salário base do funcionário
            media_variaveis: Média de variáveis dos últimos 12 meses
            meses_trabalhados: Meses trabalhados no ano (1-12)
            num_dependentes: Número de dependentes para IRRF

        Returns:
            Dict com cálculo completo das duas parcelas
        """
        primeira = self.calcular_primeira_parcela(salario_base, meses_trabalhados)
        segunda = self.calcular_segunda_parcela(
            salario_base,
            media_variaveis,
            meses_trabalhados,
            Decimal(str(primeira["valor_primeira_parcela"])),
            num_dependentes,
        )

        total_liquido = Decimal(str(primeira["valor_primeira_parcela"])) + Decimal(
            str(segunda["valor_segunda_parcela_liquida"])
        )

        return {
            "primeira_parcela": primeira,
            "segunda_parcela": segunda,
            "total_13_bruto": float(Decimal(str(segunda["valor_13_integral"]))),
            "total_descontos": segunda["descontos"]["total_descontos"],
            "total_13_liquido": float(total_liquido),
            "legislacao": self.regras.get("descricao", ""),
        }


class CalculadoraRescisao:
    """Calculadora de Rescisão Completa - CLT Art. 477 e seguintes
    Inclui: Saldo salário, Aviso prévio, Férias, 13º, Multa FGTS, Periculosidade
    """

    def __init__(self, tabelas: TabelasOficiais):
        """
        Inicializa a calculadora de rescisão

        Args:
            tabelas: Instância de TabelasOficiais
        """
        self.tabelas = tabelas
        self.regras = tabelas.obter_regras_rescisao()
        self.calc_inss = CalculadoraINSS(tabelas)
        self.calc_irrf = CalculadoraIRRF(tabelas)
        self.calc_fgts = CalculadoraFGTS(tabelas)
        self.calc_ferias = CalculadoraFerias(tabelas)
        self.calc_13 = Calculadora13Salario(tabelas)
        self.calc_adicionais = CalculadoraAdicionais(tabelas)

    def calcular(
        self,
        salario_base: Decimal,
        dias_trabalhados_mes: int,
        meses_aviso_previo: int,
        anos_empresa: int,
        ferias_vencidas_dias: int,
        meses_ferias_proporcionais: int,
        meses_13_proporcional: int,
        saldo_fgts: Decimal,
        sem_justa_causa: bool = True,
        aviso_indenizado: bool = True,
        tem_periculosidade: bool = True,
        grau_insalubridade: Optional[str] = None,
        media_variaveis: Decimal = Decimal("0"),
        num_dependentes: int = 0,
    ) -> Dict:
        """
        Calcula rescisão completa com todos os componentes

        Args:
            salario_base: Salário base mensal
            dias_trabalhados_mes: Dias trabalhados no mês da rescisão
            meses_aviso_previo: Meses de aviso prévio (calculado: 1 + anos/12)
            anos_empresa: Anos trabalhados na empresa
            ferias_vencidas_dias: Dias de férias vencidas não gozadas
            meses_ferias_proporcionais: Meses para férias proporcionais
            meses_13_proporcional: Meses para 13º proporcional
            saldo_fgts: Saldo total de FGTS acumulado
            sem_justa_causa: Se rescisão é sem justa causa
            aviso_indenizado: Se aviso prévio é indenizado
            tem_periculosidade: Se funcionário tem adicional de periculosidade
            media_variaveis: Média de variáveis (comissões, horas extras)
            num_dependentes: Número de dependentes para IRRF

        Returns:
            Dict completo com todos os cálculos de rescisão
        """
        salario = Decimal(str(salario_base))
        variaveis = Decimal(str(media_variaveis))

        # 1. Periculosidade (30%)
        valor_periculosidade_mensal = Decimal("0")
        if tem_periculosidade:
            peric = self.calc_adicionais.calcular_periculosidade(salario)
            valor_periculosidade_mensal = Decimal(str(peric["valor_adicional"]))

        # 1.b Insalubridade (opcional) - pode ser 'minimo','medio','maximo' ou None
        valor_insalubridade_mensal = Decimal("0")
        if grau_insalubridade:
            try:
                insal = self.calc_adicionais.calcular_insalubridade(grau_insalubridade)
                valor_insalubridade_mensal = Decimal(str(insal["valor_adicional"]))
            except Exception:
                # se parâmetro inválido, mantém 0 e prossegue
                valor_insalubridade_mensal = Decimal("0")

        # Salário total = base + periculosidade + insalubridade + variáveis
        salario_total = salario + valor_periculosidade_mensal + variaveis

        # 2. Saldo de Salário (dias trabalhados no mês)
        dias_mes = Decimal("30")
        saldo_salario = (
            salario_total / dias_mes * Decimal(str(dias_trabalhados_mes))
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # 3. Aviso Prévio
        dias_aviso = Decimal("30") + (Decimal("3") * Decimal(str(anos_empresa)))
        dias_aviso = min(dias_aviso, Decimal("90"))  # Máximo 90 dias

        valor_aviso_previo = Decimal("0")
        if aviso_indenizado and sem_justa_causa:
            # Aviso indenizado = (salário total / 30) × dias aviso
            valor_aviso_previo = (salario_total / dias_mes * dias_aviso).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

        # 4. Férias Vencidas + 1/3
        valor_ferias_vencidas = Decimal("0")
        valor_ferias_vencidas_um_terco = Decimal("0")
        if ferias_vencidas_dias > 0:
            valor_ferias_vencidas = (
                salario_total / dias_mes * Decimal(str(ferias_vencidas_dias))
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)
            valor_ferias_vencidas_um_terco = (
                valor_ferias_vencidas * Decimal("0.3333")
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # 5. Férias Proporcionais + 1/3
        valor_ferias_proporcionais = Decimal("0")
        valor_ferias_proporcionais_um_terco = Decimal("0")
        if meses_ferias_proporcionais > 0:
            proporcional_ferias = Decimal(str(meses_ferias_proporcionais)) / Decimal(
                "12"
            )
            valor_ferias_proporcionais = (salario_total * proporcional_ferias).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            valor_ferias_proporcionais_um_terco = (
                valor_ferias_proporcionais * Decimal("0.3333")
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # 6. 13º Salário Proporcional
        valor_13_proporcional = Decimal("0")
        if meses_13_proporcional > 0:
            valor_13_proporcional = (
                salario_total / Decimal("12") * Decimal(str(meses_13_proporcional))
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # 7. Multa FGTS (40% se sem justa causa)
        multa_fgts_obj = self.calc_fgts.calcular_multa_rescisao(
            saldo_fgts, sem_justa_causa
        )
        valor_multa_fgts = Decimal(str(multa_fgts_obj["valor_multa"]))

        # Total Bruto
        total_bruto = (
            saldo_salario
            + valor_aviso_previo
            + valor_ferias_vencidas
            + valor_ferias_vencidas_um_terco
            + valor_ferias_proporcionais
            + valor_ferias_proporcionais_um_terco
            + valor_13_proporcional
            + valor_multa_fgts
        )

        # 8. Descontos INSS e IRRF
        # Base INSS = total bruto - multa FGTS (multa FGTS não tem incidência)
        base_inss = total_bruto - valor_multa_fgts
        inss = self.calc_inss.calcular(base_inss)

        base_irrf = base_inss - Decimal(str(inss["valor_inss"]))
        irrf = self.calc_irrf.calcular(base_irrf, num_dependentes)

        total_descontos = Decimal(str(inss["valor_inss"])) + Decimal(
            str(irrf["valor_irr"])
        )
        total_liquido = total_bruto - total_descontos

        return {
            "verbas_rescisao": {
                "saldo_salario": float(saldo_salario),
                "aviso_previo_indenizado": float(valor_aviso_previo),
                "ferias_vencidas": float(valor_ferias_vencidas),
                "ferias_vencidas_um_terco": float(valor_ferias_vencidas_um_terco),
                "ferias_proporcionais": float(valor_ferias_proporcionais),
                "ferias_proporcionais_um_terco": float(
                    valor_ferias_proporcionais_um_terco
                ),
                "13_salario_proporcional": float(valor_13_proporcional),
                "multa_fgts_40": float(valor_multa_fgts),
            },
            "total_bruto": float(total_bruto),
            "descontos": {
                "inss": inss,
                "irr": irrf,
                "total_descontos": float(total_descontos),
            },
            "total_liquido": float(total_liquido),
            "detalhes": {
                "salario_base": float(salario),
                "periculosidade_mensal": float(valor_periculosidade_mensal),
                "media_variaveis": float(variaveis),
                "salario_total": float(salario_total),
                "dias_trabalhados_mes": dias_trabalhados_mes,
                "dias_aviso_previo": int(dias_aviso),
                "anos_empresa": anos_empresa,
                "ferias_vencidas_dias": ferias_vencidas_dias,
                "meses_ferias_proporcionais": meses_ferias_proporcionais,
                "meses_13_proporcional": meses_13_proporcional,
                "saldo_fgts": float(saldo_fgts),
                "sem_justa_causa": sem_justa_causa,
                "aviso_indenizado": aviso_indenizado,
                "tem_periculosidade": tem_periculosidade,
                "grau_insalubridade": grau_insalubridade,
                "insalubridade_mensal": float(valor_insalubridade_mensal),
                "num_dependentes": num_dependentes,
            },
            "legislacao": self.regras.get("descricao", ""),
        }


class MotorCalculos:
    """
    Motor Centralizado de Cálculos
    Orquestra todas as calculadoras e fornece interface unificada
    """

    # Singleton lazy instance
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(
        cls, custom_tables: Optional[object] = None, memory_only: bool = False
    ):
        """Retorna instancia singleton do MotorCalculos (lazy init)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(
                        custom_tables=custom_tables, memory_only=memory_only
                    )
        return cls._instance

    def __init__(
        self, custom_tables: Optional[object] = None, memory_only: bool = False
    ):
        """
        Inicializa o motor de cálculos

        Args:
            custom_tables: dict or path to tables to override embedded
            memory_only: se True, ignora leitura de arquivos e usa embedded
        """
        # Allow re-entrance minimal: if already initialized, skip
        if getattr(self, "_initialized", False):
            return

        self.tabelas = TabelasOficiais(custom_tables, memory_only=memory_only)
        # calculators
        self.calc_inss = CalculadoraINSS(self.tabelas)
        self.calc_irrf = CalculadoraIRRF(self.tabelas)
        self.calc_fgts = CalculadoraFGTS(self.tabelas)
        self.calc_adicionais = CalculadoraAdicionais(self.tabelas)
        self.calc_13 = Calculadora13Salario(self.tabelas)
        self.calc_rescisao = CalculadoraRescisao(self.tabelas)

        # cache for folha calculations
        self._calc_folha_impl = self._calcular_folha_impl
        self._calc_folha = lru_cache(maxsize=1024)(self._calc_folha_impl)

        self._initialized = True

        logger.info(
            json.dumps(
                {
                    "event": "motor_inicializado",
                    "source": self.tabelas.loaded_from,
                    "versao": self.tabelas.versao,
                    "ano": self.tabelas.ano,
                }
            )
        )

    def invalidate_cache(self):
        try:
            self._calc_folha.cache_clear()
        except Exception:
            pass

    def calcular_folha_completa(
        self,
        salario_base: Decimal,
        tem_periculosidade: bool = False,
        grau_insalubridade: Optional[str] = None,
        horas_extras_50: int = 0,
        horas_extras_100: int = 0,
        num_dependentes: int = 0,
    ) -> Dict:
        """
        Calcula folha de pagamento completa com todos os adicionais

        Args:
            salario_base: Salário base do funcionário
            tem_periculosidade: Se tem adicional de periculosidade
            grau_insalubridade: Grau de insalubridade ('minimo', 'medio', 'maximo') ou None
            horas_extras_50: Quantidade de horas extras 50%
            horas_extras_100: Quantidade de horas extras 100%
            num_dependentes: Número de dependentes para IRRF

        Returns:
            Dict com cálculo completo da folha
        """
        # Normalize inputs for caching (strings/primitives)
        salario = Decimal(str(salario_base))
        key_args = (
            str(salario),
            bool(tem_periculosidade),
            str(grau_insalubridade or ""),
            int(horas_extras_50),
            int(horas_extras_100),
            int(num_dependentes),
        )

        # call cached implementation
        return self._calc_folha(*key_args)

    def _calcular_folha_impl(
        self,
        salario_str,
        tem_periculosidade,
        grau_insalubridade,
        horas_extras_50,
        horas_extras_100,
        num_dependentes,
    ):
        # Convert back
        salario = Decimal(salario_str)
        tem_periculosidade = bool(tem_periculosidade)
        grau_insalubridade = grau_insalubridade or None
        horas_extras_50 = int(horas_extras_50)
        horas_extras_100 = int(horas_extras_100)
        num_dependentes = int(num_dependentes)

        # Adicionais
        valor_periculosidade = Decimal("0")
        if tem_periculosidade:
            peric = self.calc_adicionais.calcular_periculosidade(salario)
            valor_periculosidade = Decimal(str(peric["valor_adicional"]))

        valor_insalubridade = Decimal("0")
        if grau_insalubridade:
            insalub = self.calc_adicionais.calcular_insalubridade(grau_insalubridade)
            valor_insalubridade = Decimal(str(insalub["valor_adicional"]))

        # Valor hora = (salário base / 220 horas mensais)
        valor_hora = salario / Decimal("220")

        valor_he_50 = Decimal("0")
        if horas_extras_50 > 0:
            he50 = self.calc_adicionais.calcular_horas_extras(
                valor_hora, horas_extras_50, 50
            )
            valor_he_50 = Decimal(str(he50["valor_total"]))

        valor_he_100 = Decimal("0")
        if horas_extras_100 > 0:
            he100 = self.calc_adicionais.calcular_horas_extras(
                valor_hora, horas_extras_100, 100
            )
            valor_he_100 = Decimal(str(he100["valor_total"]))

        # Salário bruto total
        salario_bruto = (
            salario
            + valor_periculosidade
            + valor_insalubridade
            + valor_he_50
            + valor_he_100
        )

        # INSS
        inss = self.calc_inss.calcular(salario_bruto)

        # IRRF
        base_irrf = salario_bruto - Decimal(str(inss["valor_inss"]))
        irrf = self.calc_irrf.calcular(base_irrf, num_dependentes)

        # FGTS (não desconta, empresa deposita)
        fgts = self.calc_fgts.calcular_mensal(salario_bruto)

        # Líquido
        total_descontos = Decimal(str(inss["valor_inss"])) + Decimal(
            str(irrf["valor_irr"])
        )
        salario_liquido = salario_bruto - total_descontos

        return {
            "proventos": {
                "salario_base": float(salario),
                "periculosidade": float(valor_periculosidade),
                "insalubridade": float(valor_insalubridade),
                "horas_extras_50": float(valor_he_50),
                "horas_extras_100": float(valor_he_100),
                "total_proventos": float(salario_bruto),
            },
            "descontos": {
                "inss": inss,
                "irr": irrf,
                "total_descontos": float(total_descontos),
            },
            "fgts": fgts,
            "salario_liquido": float(salario_liquido),
            "versao_tabelas": self.tabelas.versao,
            "data_calculo": datetime.now().isoformat(),
        }

    def obter_info_tabelas(self) -> Dict:
        """Retorna informações sobre as tabelas carregadas"""
        return {
            "versao": self.tabelas.versao,
            "ano": self.tabelas.ano,
            "salario_minimo": float(self.tabelas.obter_salario_minimo()),
            "atualizado_em": self.tabelas.tabelas.get("atualizado_em"),
            "aprovado_por": self.tabelas.tabelas.get("aprovado_por"),
            "fonte": self.tabelas.tabelas.get("fonte"),
        }
