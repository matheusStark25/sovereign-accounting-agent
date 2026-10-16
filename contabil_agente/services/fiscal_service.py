"""
Serviço de Integrações Oficiais e Fiscais
Gerencia eSocial, FGTS, SPED, DCTF e DIRF

Zero Dependências Obrigatórias
-----------------------------
Este módulo foi escrito para não exigir dependências externas obrigatórias.
A validação avançada de certificados pode utilizar `pyOpenSSL` (pacote
`OpenSSL`) quando disponível, mas sua ausência não impede o funcionamento
do módulo: a validação será limitada a heurísticas (data de modificação do
arquivo) e um aviso será retornado em diagnósticos.

Funcionalidades:
- eSocial: Geração e envio de eventos, tratamento de callbacks
- FGTS: Exportadores e validadores
- SPED: Geração de arquivos SPED-Contábil
- DCTF: Declaração de Débitos e Créditos Tributários Federais
- DIRF: Declaração do Imposto sobre a Renda Retido na Fonte
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import os
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional, Tuple

import asyncio
from concurrent.futures import ThreadPoolExecutor

import json
import shutil
import zipfile


# Gerenciador de evidências local (não obrigatório)
class GerenciadorEvidencias:  # type: ignore
    def __init__(self, *args, **kwargs):
        pass

    def registrar_evidencia(self, *args, **kwargs):
        return None


# Operational limits
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_SPED_BYTES = 50 * 1024 * 1024
MAX_EVENTS_PER_BATCH = 50

# Cache TTLs (seconds)
MEMORY_CACHE_TTL = 60 * 60  # 1 hour
DISK_CACHE_TTL = 60 * 60 * 24  # 24 hours


logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================================
# FUNÇÕES DE VALIDAÇÃO
# ============================================================================


def validar_cnpj(cnpj: str) -> bool:
    """Valida CNPJ usando algoritmo oficial"""
    cnpj = re.sub(r"[^0-9]", "", cnpj)
    if len(cnpj) != 14:
        return False

    # Verifica sequências inválidas
    if cnpj == cnpj[0] * 14:
        return False

    # Valida dígitos verificadores
    def calcular_digito(cnpj_parcial: str, pesos: List[int]) -> str:
        soma = sum(int(d) * p for d, p in zip(cnpj_parcial, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    digito1 = calcular_digito(cnpj[:12], pesos1)
    digito2 = calcular_digito(cnpj[:13], pesos2)

    return cnpj[-2:] == digito1 + digito2


def validar_cpf(cpf: str) -> bool:
    """Valida CPF usando algoritmo oficial"""
    cpf = re.sub(r"[^0-9]", "", cpf)
    if len(cpf) != 11:
        return False

    # Verifica sequências inválidas
    if cpf == cpf[0] * 11:
        return False

    # Valida dígitos verificadores
    def calcular_digito(cpf_parcial: str, peso_inicial: int) -> str:
        soma = sum(int(d) * p for d, p in zip(cpf_parcial, range(peso_inicial, 1, -1)))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    digito1 = calcular_digito(cpf[:9], 10)
    digito2 = calcular_digito(cpf[:10], 11)

    return cpf[-2:] == digito1 + digito2


# ============================================================================
# ENUMS E CONSTANTES
# ============================================================================


class TipoEventoESocial(Enum):
    """Tipos de eventos eSocial"""

    S1000 = "S-1000"  # Informações do Empregador
    S1010 = "S-1010"  # Tabela de Rubricas
    S1200 = "S-1200"  # Remuneração do Trabalhador
    S1210 = "S-1210"  # Pagamentos de Rendimentos do Trabalho
    S2190 = "S-2190"  # Admissão de Trabalhador
    S2200 = "S-2200"  # Cadastramento Inicial do Vínculo
    S2206 = "S-2206"  # Alteração de Contrato de Trabalho
    S2230 = "S-2230"  # Afastamento Temporário
    S2299 = "S-2299"  # Desligamento
    S2300 = "S-2300"  # Trabalhador Sem Vínculo - Início
    S3000 = "S-3000"  # Exclusão de Eventos


class StatusEnvioESocial(Enum):
    """Status de envio de eventos eSocial"""

    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    SUCESSO = "sucesso"
    ERRO_VALIDACAO = "erro_validacao"
    ERRO_ENVIO = "erro_envio"
    REJEITADO = "rejeitado"


class TipoArquivoFiscal(Enum):
    """Tipos de arquivos fiscais"""

    SPED_CONTABIL = "sped_contabil"
    SPED_FISCAL = "sped_fiscal"
    SPED_CONTRIBUICOES = "sped_contribuicoes"
    DCTF = "dct"
    DIRF = "dir"
    GFIP = "gfip"


# ============================================================================
# INTERFACES E ADAPTERS (PADRÃO ADAPTER)
# ============================================================================


class IExportadorFiscal(ABC):
    """Interface comum para exportadores fiscais (Padrão Adapter)"""

    @abstractmethod
    def gerar_arquivo(
        self,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera arquivo fiscal

        Args:
            dados: Dados para geração do arquivo
            periodo: Tupla (data_inicio, data_fim)
            caminho_saida: Caminho do arquivo de saída

        Returns:
            Caminho do arquivo gerado
        """
        pass

    @abstractmethod
    def validar_arquivo(self, caminho_arquivo: str) -> Dict:
        """
        Valida arquivo fiscal

        Args:
            caminho_arquivo: Caminho do arquivo a validar

        Returns:
            Dict com resultado da validação
        """
        pass


# ============================================================================
# EXPORTADORES FISCAIS
# ============================================================================


class ExportadorSPED(IExportadorFiscal):
    """Exportador de arquivos SPED-Contábil"""

    def __init__(self, tipo_sped: TipoArquivoFiscal = TipoArquivoFiscal.SPED_CONTABIL):
        """
        Inicializa exportador SPED

        Args:
            tipo_sped: Tipo de SPED (contábil, fiscal, contribuições)
        """
        self.tipo_sped = tipo_sped
        self.versao_layout = "015"  # Versão atual do layout SPED
        logger.info(f"Exportador SPED inicializado: {tipo_sped.value}")

    def gerar_arquivo(
        self,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera arquivo SPED-Contábil

        Args:
            dados: Dados contábeis (plano de contas, lançamentos, etc.)
            periodo: Tupla (data_inicio, data_fim)
            caminho_saida: Caminho do arquivo de saída

        Returns:
            Caminho do arquivo gerado
        """
        logger.info(
            f"Gerando arquivo SPED: {self.tipo_sped.value} para período {periodo[0]} a {periodo[1]}"
        )
        if caminho_saida is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            caminho_saida = f"sped_{self.tipo_sped.value}_{timestamp}.txt"

        caminho_arquivo = Path(caminho_saida)
        caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)

        # Gera conteúdo do arquivo SPED
        linhas = []

        # Bloco 0: Abertura, Identificação e Referências
        linhas.append(self._gerar_registro_0000(dados, periodo))
        linhas.append(self._gerar_registro_0001(dados))
        linhas.append(self._gerar_registro_0007(dados))
        linhas.extend(self._gerar_registros_plano_contas(dados))
        linhas.append(
            "|0990|"
            + str(len([linha for linha in linhas if linha.startswith("|0")]))
            + "|"
        )

        # Bloco I: Lançamentos Contábeis
        linhas.append("|I001|0|")
        linhas.extend(self._gerar_registros_lancamentos(dados, periodo))
        linhas.append(
            "|I990|"
            + str(len([linha for linha in linhas if linha.startswith("|I")]))
            + "|"
        )

        # Bloco J: Demonstrações Contábeis
        linhas.append("|J001|0|")
        linhas.extend(self._gerar_registros_demonstracoes(dados, periodo))
        linhas.append(
            "|J990|"
            + str(len([linha for linha in linhas if linha.startswith("|J")]))
            + "|"
        )

        # Bloco 9: Controle e Encerramento
        linhas.append("|9001|0|")
        linhas.extend(self._gerar_totalizadores_blocos(linhas))
        linhas.append(
            "|9990|"
            + str(len([linha for linha in linhas if linha.startswith("|9")]))
            + "|"
        )
        linhas.append("|9999|" + str(len(linhas) + 1) + "|")

        # Escreve arquivo
        with open(caminho_arquivo, "w", encoding="ISO-8859-1") as f:
            f.write("\n".join(linhas))

        logger.info(f"Arquivo SPED gerado: {caminho_arquivo} ({len(linhas)} linhas)")
        return str(caminho_arquivo)

    def validar_arquivo(self, caminho_arquivo: str) -> Dict:
        """
        Valida arquivo SPED

        Args:
            caminho_arquivo: Caminho do arquivo a validar

        Returns:
            Dict com resultado da validação
        """
        logger.info(f"Validando arquivo SPED: {caminho_arquivo}")

        erros = []
        avisos = []

        try:
            with open(caminho_arquivo, "r", encoding="ISO-8859-1") as f:
                linhas = f.readlines()

            # Valida estrutura básica
            if not linhas[0].startswith("|0000|"):
                erros.append("Arquivo não inicia com registro 0000")

            if not linhas[-1].startswith("|9999|"):
                erros.append("Arquivo não termina com registro 9999")

            # Valida quantidade de registros
            total_registros = len(linhas)
            registro_9999 = linhas[-1].split("|")
            total_declarado = int(registro_9999[2]) if len(registro_9999) >= 3 else 0

            if total_registros != total_declarado:
                erros.append(
                    f"Total de registros ({total_registros}) != Total declarado ({total_declarado})"
                )

            # Valida blocos obrigatórios
            blocos_encontrados = set()
            for linha in linhas:
                if linha.startswith("|"):
                    bloco = linha[1]
                    blocos_encontrados.add(bloco)

            blocos_obrigatorios = {"0", "9"}
            blocos_faltantes = blocos_obrigatorios - blocos_encontrados

            if blocos_faltantes:
                erros.append(f"Blocos obrigatórios faltantes: {blocos_faltantes}")

            valido = len(erros) == 0

            return {
                "valido": valido,
                "total_registros": total_registros,
                "blocos_encontrados": list(blocos_encontrados),
                "erros": erros,
                "avisos": avisos,
            }

        except Exception as e:
            logger.error(f"Erro ao validar arquivo SPED: {e}")
            return {
                "valido": False,
                "erros": [f"Erro ao processar arquivo: {str(e)}"],
                "avisos": [],
            }

    # Métodos auxiliares para geração de registros

    def _gerar_registro_0000(
        self, dados: Dict, periodo: Tuple[datetime, datetime]
    ) -> str:
        """Gera registro 0000 (Abertura do arquivo)"""
        cnpj = (
            dados.get("empresa", {})
            .get("cnpj", "")
            .replace(".", "")
            .replace("/", "")
            .replace("-", "")
        )
        nome = dados.get("empresa", {}).get("nome", "")
        data_ini = periodo[0].strftime("%d%m%Y")
        data_fin = periodo[1].strftime("%d%m%Y")

        return f"|0000|015|0|{data_ini}|{data_fin}|{nome}|{cnpj}|UF|IM|MUNIC|"

    def _gerar_registro_0001(self, dados: Dict) -> str:
        """Gera registro 0001 (Abertura do Bloco 0)"""
        return "|0001|0|"

    def _gerar_registro_0007(self, dados: Dict) -> str:
        """Gera registro 0007 (Outras inscrições cadastrais)"""
        cnpj = (
            dados.get("empresa", {})
            .get("cnpj", "")
            .replace(".", "")
            .replace("/", "")
            .replace("-", "")
        )
        return f"|0007|{cnpj}|01|"

    def _gerar_registros_plano_contas(self, dados: Dict) -> List[str]:
        """Gera registros do plano de contas"""
        registros = []
        plano_contas = dados.get("plano_contas", [])

        for conta in plano_contas:
            codigo = conta.get("codigo", "")
            nome = conta.get("nome", "")
            nivel = conta.get("nivel", 1)
            natureza = conta.get("natureza", "01")  # 01=Ativo, 02=Passivo, etc.

            registros.append(f"|I050|{codigo}|{nome}|{nivel}|{natureza}|")

        return registros

    def _gerar_registros_lancamentos(
        self, dados: Dict, periodo: Tuple[datetime, datetime]
    ) -> List[str]:
        """Gera registros de lançamentos contábeis"""
        registros = []
        lancamentos = dados.get("lancamentos", [])

        for lanc in lancamentos:
            data_lanc = lanc.get("data", datetime.now()).strftime("%d%m%Y")
            conta_debito = lanc.get("conta_debito", "")
            conta_credito = lanc.get("conta_credito", "")
            valor = lanc.get("valor", Decimal("0.00"))
            historico = lanc.get("historico", "")

            registros.append(
                f"|I200|{data_lanc}|{conta_debito}|{conta_credito}|{valor:.2f}|{historico}|"
            )

        return registros

    def _gerar_registros_demonstracoes(
        self, dados: Dict, periodo: Tuple[datetime, datetime]
    ) -> List[str]:
        """Gera registros de demonstrações contábeis"""
        registros = []
        demonstracoes = dados.get("demonstracoes", {})

        # Balancete
        balancete = demonstracoes.get("balancete", [])
        for item in balancete:
            conta = item.get("conta", "")
            saldo_inicial = item.get("saldo_inicial", Decimal("0.00"))
            debitos = item.get("debitos", Decimal("0.00"))
            creditos = item.get("creditos", Decimal("0.00"))
            saldo_final = item.get("saldo_final", Decimal("0.00"))

            registros.append(
                f"|J100|{conta}|{saldo_inicial:.2f}|{debitos:.2f}|{creditos:.2f}|{saldo_final:.2f}|"
            )

        return registros

    def _gerar_totalizadores_blocos(self, linhas: List[str]) -> List[str]:
        """Gera registros totalizadores de blocos"""
        totalizadores = []

        blocos = {}
        for linha in linhas:
            if linha.startswith("|"):
                bloco = linha[1]
                blocos[bloco] = blocos.get(bloco, 0) + 1

        for bloco, quantidade in sorted(blocos.items()):
            if bloco != "9":  # Não conta o próprio bloco 9
                totalizadores.append(f"|9900|{bloco}990|{quantidade}|")

        return totalizadores


class ExportadorDCTF(IExportadorFiscal):
    """Exportador de DCTF (Declaração de Débitos e Créditos Tributários Federais)"""

    def __init__(self):
        """Inicializa exportador DCTF"""
        logger.info("Exportador DCTF inicializado")

    def gerar_arquivo(
        self,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera arquivo DCTF

        Args:
            dados: Dados tributários (impostos, contribuições, etc.)
            periodo: Tupla (data_inicio, data_fim)
            caminho_saida: Caminho do arquivo de saída

        Returns:
            Caminho do arquivo gerado
        """
        logger.info(f"Gerando arquivo DCTF para período {periodo[0]} a {periodo[1]}")

        if caminho_saida is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mes_ano = periodo[0].strftime("%m%Y")
            caminho_saida = f"dctf_{mes_ano}_{timestamp}.txt"

        caminho_arquivo = Path(caminho_saida)
        caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)

        # Estrutura básica DCTF
        linhas = []

        # Cabeçalho
        cnpj = (
            dados.get("empresa", {})
            .get("cnpj", "")
            .replace(".", "")
            .replace("/", "")
            .replace("-", "")
        )
        mes_ano = periodo[0].strftime("%m%Y")
        linhas.append(f"DCTF|{cnpj}|{mes_ano}|")

        # Débitos (impostos a pagar)
        debitos = dados.get("debitos", [])
        for debito in debitos:
            codigo_receita = debito.get("codigo_receita", "")
            valor_principal = debito.get("valor_principal", Decimal("0.00"))
            multa = debito.get("multa", Decimal("0.00"))
            juros = debito.get("juros", Decimal("0.00"))

            linhas.append(
                f"DEBITO|{codigo_receita}|{valor_principal:.2f}|{multa:.2f}|{juros:.2f}|"
            )

        # Créditos (compensações)
        creditos = dados.get("creditos", [])
        for credito in creditos:
            codigo_receita = credito.get("codigo_receita", "")
            valor = credito.get("valor", Decimal("0.00"))

            linhas.append(f"CREDITO|{codigo_receita}|{valor:.2f}|")

        # Totalizador
        total_debitos = sum(d.get("valor_principal", Decimal("0.00")) for d in debitos)
        total_creditos = sum(c.get("valor", Decimal("0.00")) for c in creditos)
        saldo = total_debitos - total_creditos

        linhas.append(f"TOTAL|{total_debitos:.2f}|{total_creditos:.2f}|{saldo:.2f}|")

        # Escreve arquivo
        with open(caminho_arquivo, "w", encoding="ISO-8859-1") as f:
            f.write("\n".join(linhas))

        logger.info(f"Arquivo DCTF gerado: {caminho_arquivo} ({len(linhas)} linhas)")
        return str(caminho_arquivo)

    def validar_arquivo(self, caminho_arquivo: str) -> Dict:
        """
        Valida arquivo DCTF

        Args:
            caminho_arquivo: Caminho do arquivo a validar

        Returns:
            Dict com resultado da validação
        """
        logger.info(f"Validando arquivo DCTF: {caminho_arquivo}")

        erros = []
        avisos = []

        try:
            with open(caminho_arquivo, "r", encoding="ISO-8859-1") as f:
                linhas = f.readlines()

            if not linhas[0].startswith("DCTF|"):
                erros.append("Arquivo não inicia com registro DCTF")

            if not linhas[-1].startswith("TOTAL|"):
                erros.append("Arquivo não termina com registro TOTAL")

            valido = len(erros) == 0

            return {
                "valido": valido,
                "total_registros": len(linhas),
                "erros": erros,
                "avisos": avisos,
            }

        except Exception as e:
            logger.error(f"Erro ao validar arquivo DCTF: {e}")
            return {
                "valido": False,
                "erros": [f"Erro ao processar arquivo: {str(e)}"],
                "avisos": [],
            }


class ExportadorDIRF(IExportadorFiscal):
    """Exportador de DIRF (Declaração do Imposto sobre a Renda Retido na Fonte)"""

    def __init__(self):
        """Inicializa exportador DIRF"""
        logger.info("Exportador DIRF inicializado")

    def gerar_arquivo(
        self,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera arquivo DIRF

        Args:
            dados: Dados de rendimentos e retenções
            periodo: Tupla (data_inicio, data_fim)
            caminho_saida: Caminho do arquivo de saída

        Returns:
            Caminho do arquivo gerado
        """
        logger.info(f"Gerando arquivo DIRF para período {periodo[0]} a {periodo[1]}")

        if caminho_saida is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ano = periodo[0].year
            caminho_saida = f"dirf_{ano}_{timestamp}.txt"

        caminho_arquivo = Path(caminho_saida)
        caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)

        linhas = []

        # Registro DIRF (Identificação)
        cnpj = (
            dados.get("empresa", {})
            .get("cnpj", "")
            .replace(".", "")
            .replace("/", "")
            .replace("-", "")
        )
        ano_calendario = periodo[0].year
        linhas.append(f"DIRF|{cnpj}|{ano_calendario}|")

        # Registro DECPJ (Declarante Pessoa Jurídica)
        nome_empresa = dados.get("empresa", {}).get("nome", "")
        linhas.append(f"DECPJ|{cnpj}|{nome_empresa}|")

        # Registros de beneficiários
        beneficiarios = dados.get("beneficiarios", [])
        for benef in beneficiarios:
            cpf = benef.get("cp", "").replace(".", "").replace("-", "")
            nome = benef.get("nome", "")
            rendimentos = benef.get("rendimentos", Decimal("0.00"))
            ir_retido = benef.get("ir_retido", Decimal("0.00"))
            inss = benef.get("inss", Decimal("0.00"))

            # BPFDEC (Beneficiário Pessoa Física)
            linhas.append(f"BPFDEC|{cpf}|{nome}|")

            # RTRT (Rendimentos do Trabalho)
            linhas.append(f"RTRT|{rendimentos:.2f}|{ir_retido:.2f}|{inss:.2f}|")

        # Totalizador
        total_rendimentos = sum(
            b.get("rendimentos", Decimal("0.00")) for b in beneficiarios
        )
        total_ir = sum(b.get("ir_retido", Decimal("0.00")) for b in beneficiarios)

        linhas.append(f"TOTALIZADOR|{total_rendimentos:.2f}|{total_ir:.2f}|")

        # Escreve arquivo
        with open(caminho_arquivo, "w", encoding="ISO-8859-1") as f:
            f.write("\n".join(linhas))

        logger.info(f"Arquivo DIRF gerado: {caminho_arquivo} ({len(linhas)} linhas)")
        return str(caminho_arquivo)

    def validar_arquivo(self, caminho_arquivo: str) -> Dict:
        """
        Valida arquivo DIRF

        Args:
            caminho_arquivo: Caminho do arquivo a validar

        Returns:
            Dict com resultado da validação
        """
        logger.info(f"Validando arquivo DIRF: {caminho_arquivo}")

        erros = []
        avisos = []

        try:
            with open(caminho_arquivo, "r", encoding="ISO-8859-1") as f:
                linhas = f.readlines()

            if not linhas[0].startswith("DIRF|"):
                erros.append("Arquivo não inicia com registro DIRF")

            valido = len(erros) == 0

            return {
                "valido": valido,
                "total_registros": len(linhas),
                "erros": erros,
                "avisos": avisos,
            }

        except Exception as e:
            logger.error(f"Erro ao validar arquivo DIRF: {e}")
            return {
                "valido": False,
                "erros": [f"Erro ao processar arquivo: {str(e)}"],
                "avisos": [],
            }


# ============================================================================
# SERVIÇO eSocial
# ============================================================================


class ServicoESocial:
    """Serviço para geração e envio de eventos eSocial com tratamento de callbacks"""

    def __init__(
        self,
        ambiente: str = "producao-restrita",
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
    ):
        """
        Inicializa serviço eSocial

        Args:
            ambiente: Ambiente (producao, producao-restrita)
            gerenciador_evidencias: Gerenciador de evidências
        """
        self.ambiente = ambiente
        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()

        # URLs dos webservices por ambiente
        self.urls = {
            "producao-restrita": "https://webservices.producaorestrita.esocial.gov.br/servicos/empregador/",
            "producao": "https://webservices.esocial.gov.br/servicos/empregador/",
        }

        self.url_base = self.urls.get(ambiente, self.urls["producao-restrita"])

        logger.info(f"Serviço eSocial inicializado - Ambiente: {ambiente}")

    def gerar_evento_xml(self, tipo_evento: TipoEventoESocial, dados: Dict) -> str:
        """
        Gera XML de evento eSocial

        Args:
            tipo_evento: Tipo do evento eSocial
            dados: Dados do evento

        Returns:
            String com XML do evento

        Raises:
            ValueError: Se dados obrigatórios estão ausentes ou inválidos
        """
        logger.info(f"Gerando evento eSocial: {tipo_evento.value}")

        # Validação de dados obrigatórios
        if not dados:
            raise ValueError("Dados do evento não podem estar vazios")

        empregador = dados.get("empregador", {})
        if not empregador:
            raise ValueError("Dados do empregador são obrigatórios")

        cnpj = empregador.get("cnpj", "")
        if not cnpj:
            raise ValueError("CNPJ do empregador é obrigatório")

        # Valida CNPJ
        if not validar_cnpj(cnpj):
            logger.warning(f"CNPJ inválido: {cnpj} - Continuando geração")

        # Namespace padrão eSocial
        namespace = "http://www.esocial.gov.br/schema/evt/"

        # Cria elemento raiz
        root = ET.Element("eSocial", xmlns=namespace)
        root.set("versao", "S-1.1")

        # Cria evento específico
        evento = ET.SubElement(root, tipo_evento.value)

        # ID do evento (formato: ID + tipo + CNPJ + timestamp)
        cnpj_numeros = re.sub(r"[^0-9]", "", cnpj)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        id_evento = f"ID{tipo_evento.value.replace('-', '')}{cnpj_numeros}{timestamp}"
        evento.set("Id", id_evento)

        # Adiciona dados específicos do evento
        if tipo_evento == TipoEventoESocial.S2190:
            self._adicionar_dados_admissao(evento, dados)
        elif tipo_evento == TipoEventoESocial.S2299:
            self._adicionar_dados_desligamento(evento, dados)
        elif tipo_evento == TipoEventoESocial.S1200:
            self._adicionar_dados_remuneracao(evento, dados)
        else:
            # Estrutura genérica
            info_evento = ET.SubElement(evento, "infoEvento")
            for chave, valor in dados.items():
                elem = ET.SubElement(info_evento, chave)
                elem.text = str(valor)

        # Converte para string XML
        xml_string = ET.tostring(root, encoding="unicode", method="xml")

        # Formata XML (adiciona indentação)
        xml_formatado = self._formatar_xml(xml_string)

        logger.debug(f"XML gerado: {len(xml_formatado)} caracteres")
        return xml_formatado

    def enviar_evento(self, xml_evento: str, lote: Optional[str] = None) -> Dict:
        """
        Envia evento eSocial para o governo (simulação)

        NOTA: Em produção, usar biblioteca requests + certificado digital A1/A3

        Args:
            xml_evento: XML do evento a enviar
            lote: Número do lote (opcional)

        Returns:
            Dict com resultado do envio

        Raises:
            ValueError: Se XML é inválido ou vazio
        """
        logger.info("Enviando evento eSocial...")

        # Validações
        if not xml_evento or not xml_evento.strip():
            raise ValueError("XML do evento não pode estar vazio")

        # Valida que é XML válido
        try:
            ET.fromstring(xml_evento)
        except ET.ParseError as e:
            raise ValueError(f"XML malformado: {e}")

        # Valida tamanho do XML (máximo 5MB)
        tamanho_kb = len(xml_evento.encode("utf-8")) / 1024
        if tamanho_kb > 5120:  # 5MB
            raise ValueError(f"XML muito grande: {tamanho_kb:.2f}KB (máximo 5MB)")

        logger.debug(f"XML validado: {tamanho_kb:.2f}KB")

        # Calcula hash do XML para evidência
        hash_xml = hashlib.sha256(xml_evento.encode("utf-8")).hexdigest()

        # SIMULAÇÃO: Em produção, fazer requisição SOAP ao webservice
        # import requests
        # headers = {'Content-Type': 'application/xml'}
        # response = requests.post(url_envio, data=xml_evento, headers=headers, cert=certificado)

        # Simula resposta bem-sucedida
        protocolo = f"1.1.{datetime.now().strftime('%Y%m%d%H%M%S')}.{hash_xml[:16]}"

        resultado = {
            "status": StatusEnvioESocial.SUCESSO.value,
            "protocolo": protocolo,
            "data_envio": datetime.now().isoformat(),
            "hash_xml": hash_xml,
            "lote": lote or "LOTE001",
            "mensagem": "Evento enviado com sucesso (SIMULAÇÃO)",
        }

        # Registra evidência
        self.gerenciador.registrar_evidencia(
            tipo="envio_esocial",
            descricao=f"Envio de evento eSocial - Protocolo: {protocolo}",
            dados={
                "protocolo": protocolo,
                "hash_xml": hash_xml,
                "status": resultado["status"],
                "lote": resultado["lote"],
            },
        )

        logger.info(f"Evento enviado - Protocolo: {protocolo}")
        return resultado

    def processar_callback(self, xml_retorno: str) -> Dict:
        """
        Processa callback/retorno do governo (assíncrono)

        Args:
            xml_retorno: XML de retorno do governo

        Returns:
            Dict com informações processadas do retorno
        """
        logger.info("Processando callback eSocial...")

        try:
            # Parse do XML de retorno
            root = ET.fromstring(xml_retorno)

            # Extrai informações do retorno
            protocolo = root.find(".//protocolo")
            status_elem = root.find(".//status")
            mensagem = root.find(".//mensagem")

            resultado = {
                "protocolo": protocolo.text if protocolo is not None else None,
                "status": (
                    status_elem.text if status_elem is not None else "desconhecido"
                ),
                "mensagem": mensagem.text if mensagem is not None else "",
                "processado_em": datetime.now().isoformat(),
            }

            # Verifica se há erros
            erros = root.findall(".//erro")
            if erros:
                resultado["erros"] = []
                for erro in erros:
                    codigo = erro.find("codigo")
                    descricao = erro.find("descricao")
                    resultado["erros"].append(
                        {
                            "codigo": codigo.text if codigo is not None else "",
                            "descricao": (
                                descricao.text if descricao is not None else ""
                            ),
                        }
                    )

                resultado["status"] = StatusEnvioESocial.ERRO_VALIDACAO.value

            # Registra evidência do callback
            hash_retorno = hashlib.sha256(xml_retorno.encode("utf-8")).hexdigest()
            self.gerenciador.registrar_evidencia(
                tipo="callback_esocial",
                descricao=f"Retorno eSocial processado - Protocolo: {resultado.get('protocolo')}",
                dados={
                    "protocolo": resultado.get("protocolo"),
                    "status": resultado["status"],
                    "hash_retorno": hash_retorno,
                    "erros": resultado.get("erros", []),
                },
            )

            logger.info(f"Callback processado - Status: {resultado['status']}")
            return resultado

        except ET.ParseError as e:
            logger.error(f"Erro ao processar XML de retorno: {e}")
            return {
                "status": StatusEnvioESocial.ERRO_ENVIO.value,
                "mensagem": f"Erro ao processar retorno: {str(e)}",
                "processado_em": datetime.now().isoformat(),
            }

    # Métodos auxiliares

    def _adicionar_dados_admissao(self, evento: ET.Element, dados: Dict):
        """Adiciona dados de admissão ao evento S-2190"""
        info_adm = ET.SubElement(evento, "evtAdmissao")

        trabalhador = ET.SubElement(info_adm, "trabalhador")
        ET.SubElement(trabalhador, "cpfTrab").text = dados.get("cp", "")
        ET.SubElement(trabalhador, "nmTrab").text = dados.get("nome", "")
        ET.SubElement(trabalhador, "dtNasc").text = dados.get("data_nascimento", "")

        vinculo = ET.SubElement(info_adm, "vinculo")
        ET.SubElement(vinculo, "dtAdm").text = dados.get("data_admissao", "")
        ET.SubElement(vinculo, "cargo").text = dados.get("cargo", "")
        ET.SubElement(vinculo, "salario").text = str(dados.get("salario", "0.00"))

    def _adicionar_dados_desligamento(self, evento: ET.Element, dados: Dict):
        """Adiciona dados de desligamento ao evento S-2299"""
        info_desl = ET.SubElement(evento, "evtDeslig")

        ET.SubElement(info_desl, "cpfTrab").text = dados.get("cp", "")
        ET.SubElement(info_desl, "dtDeslig").text = dados.get("data_desligamento", "")
        ET.SubElement(info_desl, "mtvDeslig").text = dados.get("motivo", "01")

    def _adicionar_dados_remuneracao(self, evento: ET.Element, dados: Dict):
        """Adiciona dados de remuneração ao evento S-1200"""
        info_remun = ET.SubElement(evento, "evtRemun")

        ET.SubElement(info_remun, "cpfTrab").text = dados.get("cp", "")
        ET.SubElement(info_remun, "perRe").text = dados.get("periodo_referencia", "")
        ET.SubElement(info_remun, "vlrRemun").text = str(
            dados.get("valor_remuneracao", "0.00")
        )

        # Rubricas
        rubricas = dados.get("rubricas", [])
        for rubrica in rubricas:
            dmDev = ET.SubElement(info_remun, "dmDev")
            ET.SubElement(dmDev, "codRubr").text = rubrica.get("codigo", "")
            ET.SubElement(dmDev, "vrRubr").text = str(rubrica.get("valor", "0.00"))

    def _formatar_xml(self, xml_string: str) -> str:
        """Formata XML com indentação"""
        try:
            import xml.dom.minidom

            dom = xml.dom.minidom.parseString(xml_string)
            return dom.toprettyxml(indent="  ")
        except Exception:
            return xml_string


# ============================================================================
# SERVIÇO FGTS
# ============================================================================


class ServicoFGTS:
    """Serviço para geração de arquivos FGTS (SEFIP/GFIP)"""

    def __init__(self, gerenciador_evidencias: Optional[GerenciadorEvidencias] = None):
        """
        Inicializa serviço FGTS

        Args:
            gerenciador_evidencias: Gerenciador de evidências
        """
        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()
        logger.info("Serviço FGTS inicializado")

    def gerar_arquivo_gfip(
        self,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera arquivo GFIP (Guia de Recolhimento do FGTS e Informações à Previdência Social)

        Args:
            dados: Dados da folha e FGTS
            periodo: Tupla (data_inicio, data_fim)
            caminho_saida: Caminho do arquivo de saída

        Returns:
            Caminho do arquivo gerado
        """
        logger.info(f"Gerando arquivo GFIP para período {periodo[0]} a {periodo[1]}")

        if caminho_saida is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mes_ano = periodo[0].strftime("%m%Y")
            caminho_saida = f"gfip_{mes_ano}_{timestamp}.txt"

        caminho_arquivo = Path(caminho_saida)
        caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)

        linhas = []

        # Tipo 10 - Cadastro da Empresa
        cnpj = (
            dados.get("empresa", {})
            .get("cnpj", "")
            .replace(".", "")
            .replace("/", "")
            .replace("-", "")
        )
        nome = dados.get("empresa", {}).get("nome", "")
        linhas.append(f"10{cnpj}{nome}")

        # Tipo 20 - Dados da competência
        competencia = periodo[0].strftime("%m%Y")
        linhas.append(f"20{competencia}")

        # Tipo 30 - Trabalhadores
        trabalhadores = dados.get("trabalhadores", [])
        for trab in trabalhadores:
            pis = trab.get("pis", "").replace(".", "").replace("-", "")
            nome_trab = trab.get("nome", "")
            salario = trab.get("salario", Decimal("0.00"))
            fgts = salario * Decimal("0.08")  # 8% de FGTS

            linhas.append(f"30{pis}{nome_trab}{salario:.2f}{fgts:.2f}")

        # Tipo 90 - Totalizador
        total_fgts = sum(
            trab.get("salario", Decimal("0.00")) * Decimal("0.08")
            for trab in trabalhadores
        )
        linhas.append(f"90{total_fgts:.2f}")

        # Escreve arquivo
        with open(caminho_arquivo, "w", encoding="ISO-8859-1") as f:
            f.write("\n".join(linhas))

        # Registra evidência
        hash_arquivo = hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()

        self.gerenciador.registrar_evidencia(
            tipo="geracao_gfip",
            descricao=f"Arquivo GFIP gerado - Competência: {competencia}",
            dados={
                "competencia": competencia,
                "total_trabalhadores": len(trabalhadores),
                "total_fgts": float(total_fgts),
                "hash_arquivo": hash_arquivo,
            },
            arquivo_relacionado=str(caminho_arquivo),
        )

        logger.info(f"Arquivo GFIP gerado: {caminho_arquivo}")
        return str(caminho_arquivo)

    def validar_arquivo_gfip(self, caminho_arquivo: str) -> Dict:
        """
        Valida arquivo GFIP

        Args:
            caminho_arquivo: Caminho do arquivo a validar

        Returns:
            Dict com resultado da validação
        """
        logger.info(f"Validando arquivo GFIP: {caminho_arquivo}")

        erros = []
        avisos = []

        try:
            with open(caminho_arquivo, "r", encoding="ISO-8859-1") as f:
                linhas = f.readlines()

            if not any(line.startswith("10") for line in linhas):
                erros.append("Falta registro tipo 10 (Empresa)")

            if not any(line.startswith("20") for line in linhas):
                erros.append("Falta registro tipo 20 (Competência)")

            if not any(line.startswith("90") for line in linhas):
                erros.append("Falta registro tipo 90 (Totalizador)")

            valido = len(erros) == 0

            return {
                "valido": valido,
                "total_registros": len(linhas),
                "erros": erros,
                "avisos": avisos,
            }

        except Exception as e:
            logger.error(f"Erro ao validar arquivo GFIP: {e}")
            return {
                "valido": False,
                "erros": [f"Erro ao processar arquivo: {str(e)}"],
                "avisos": [],
            }


# ============================================================================
# SERVIÇO FISCAL PRINCIPAL
# ============================================================================


class FiscalService:
    """Serviço principal de integrações fiscais e oficiais com resiliência.

    Recursos adicionados:
    - Gerenciamento de certificado (hierarquia de busca + validação)
    - Cache hierárquico (memória + disco)
    - Métricas internas e método `get_metrics()`
    - Circuit breaker + retry para envio de lotes
    - Backup automático e retenção/compactação
    - Operações assíncronas para grandes arquivos
    - Logs estruturados com metadados
    """

    def __init__(
        self,
        ambiente_esocial: str = "producao-restrita",
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
        cert_path: Optional[str] = None,
        cache_dir: str = "cache/fiscal",
        backup_dir: str = "backup/fiscal",
        retention_days: int = 365 * 5,
        simulation_mode: bool = False,
    ):
        # Prioritize environment variables for configuration (hierarquia)
        env_cert = os.environ.get("FISCAL_CERT_PATH")
        if not env_cert:
            env_cert = cert_path

        env_cache = os.environ.get("FISCAL_CACHE_DIR") or cache_dir
        env_backup = os.environ.get("FISCAL_BACKUP_DIR") or backup_dir
        env_retention = os.environ.get("FISCAL_RETENTION_DAYS")
        if env_retention is not None:
            try:
                env_retention_val = int(env_retention)
            except Exception:
                env_retention_val = retention_days
        else:
            env_retention_val = retention_days

        env_sim = os.environ.get("FISCAL_SIMULATION")
        if env_sim is not None:
            env_sim_val = str(env_sim).lower() in ("1", "true", "yes")
        else:
            env_sim_val = bool(simulation_mode)

        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()

        # Serviços especializados
        self.esocial = ServicoESocial(ambiente_esocial, self.gerenciador)
        self.fgts = ServicoFGTS(self.gerenciador)

        # Exportadores (Padrão Adapter)
        self.exportadores: Dict[TipoArquivoFiscal, IExportadorFiscal] = {
            TipoArquivoFiscal.SPED_CONTABIL: ExportadorSPED(
                TipoArquivoFiscal.SPED_CONTABIL
            ),
            TipoArquivoFiscal.DCTF: ExportadorDCTF(),
            TipoArquivoFiscal.DIRF: ExportadorDIRF(),
        }

        # Paths (allow override by env)
        self.cache_dir = Path(env_cache)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = Path(env_backup)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = env_retention_val

        # Certificate handling (env-aware)
        self.cert_path = self._locate_certificate(env_cert)
        self.simulation_mode = env_sim_val or (self.cert_path is None)

        # Cache structures
        self._mem_cache: Dict[str, Tuple[object, float]] = {}

        # Metrics
        self._metrics = {
            "calls": 0,
            "success": 0,
            "fail": 0,
            "total_time": 0.0,
        }

        # Circuit breaker
        self._cb_failures = 0
        self._cb_state = "CLOSED"
        self._cb_open_until: Optional[float] = None
        self._cb_lock = threading.Lock()

        # Thread-safety for sending
        self._send_lock = threading.Lock()

        logger.info("FiscalService inicializado")

    # -------------------------
    # Logging helpers
    # -------------------------
    def _log(
        self,
        level: str,
        cnpj: str = "",
        tipo_evento: str = "",
        status: str = "",
        msg: str = "",
    ):
        ts = datetime.now(timezone.utc).isoformat()
        meta = f"[{ts}] [{cnpj}] [{tipo_evento}] [{status}] - {msg}"
        if level == "info":
            logger.info(meta)
        elif level == "warning":
            logger.warning(meta)
        elif level == "error":
            logger.error(meta)
        else:
            logger.debug(meta)

    # -------------------------
    # Certificate management
    # -------------------------
    def _locate_certificate(self, cert_path: Optional[str]) -> Optional[str]:
        # 1) constructor param
        if cert_path:
            if Path(cert_path).exists():
                return cert_path

        # 2) env var
        env_path = os.environ.get("CERTIFICADO_A1_PATH") or os.environ.get(
            "CERTIFICADO_PATH"
        )
        if env_path and Path(env_path).exists():
            return env_path

        # 3) platform defaults
        candidates = []
        if os.name == "nt":
            candidates.append(Path("Certificates"))
        else:
            candidates.append(Path.home() / ".certificates")

        for base in candidates:
            if base.exists():
                for p in base.iterdir():
                    if p.suffix.lower() in {".p12", ".pem", ".crt", ".cer"}:
                        return str(p)

        # Dynamic import check: warn if pyOpenSSL missing (optional only)
        try:
            import importlib.util

            if importlib.util.find_spec("OpenSSL") is None:
                logger.warning(
                    "pyOpenSSL (OpenSSL) not found: certificate parsing helpers are limited"
                )
        except Exception:
            # if importlib unavailable for some reason, just continue
            pass

        return None

    def _validate_certificate(self, cert_path: Optional[str]) -> dict:
        """Tenta validar a data de expiração do certificado se biblioteca estiver disponível.

        Se não for possível validar, devolve heurística (exists/mode_simulation).
        """
        res = {"found": False, "valid": False, "expires_at": None, "warning": None}
        if not cert_path:
            return res
        p = Path(cert_path)
        if not p.exists():
            return res
        res["found"] = True

        try:
            import importlib.util

            spec = importlib.util.find_spec("OpenSSL")
        except Exception:
            spec = None

        if spec is None:
            # OpenSSL not available: do not fail, provide heuristic and warning
            res["warning"] = (
                "pyOpenSSL not available: expiration validation limited (heuristic based on file mtime)"
            )
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                res["expires_at"] = mtime.isoformat()
            except Exception:
                res["expires_at"] = None
            res["valid"] = True
            return res

        # If available, attempt robust parsing
        try:
            OpenSSL_mod = __import__("OpenSSL")
            crypto = getattr(OpenSSL_mod, "crypto", None)
        except Exception:
            crypto = None

        try:
            data = p.read_bytes()
            if crypto is not None:
                cert = None
                try:
                    cert = crypto.load_certificate(crypto.FILETYPE_PEM, data)
                except Exception:
                    try:
                        pkcs12 = crypto.load_pkcs12(data)
                        cert = pkcs12.get_certificate()
                    except Exception:
                        cert = None

                if cert is not None:
                    try:
                        expires = datetime.strptime(
                            cert.get_notAfter().decode("ascii"), "%Y%m%d%H%M%SZ"
                        ).replace(tzinfo=timezone.utc)
                        res["expires_at"] = expires.isoformat()
                        res["valid"] = expires > datetime.now(timezone.utc)
                        return res
                    except Exception:
                        # parsing failed: fallback with warning
                        res["warning"] = (
                            "Failed to parse certificate expiry; using heuristic instead"
                        )

            # Fallback heuristic: use file modification time
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                res["expires_at"] = mtime.isoformat()
            except Exception:
                res["expires_at"] = None
            res["valid"] = True
            return res
        except Exception:
            # Last-resort: do not crash; return heuristic
            res["warning"] = "Error reading certificate file; validation limited"
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                res["expires_at"] = mtime.isoformat()
            except Exception:
                res["expires_at"] = None
            res["valid"] = True
            return res

    # -------------------------
    # Cache (mem + disk simple)
    # -------------------------
    def _mem_get(self, key: str):
        entry = self._mem_cache.get(key)
        if not entry:
            return None
        value, expires = entry
        if time.time() > expires:
            del self._mem_cache[key]
            return None
        return value

    def _mem_set(self, key: str, value, ttl: int = MEMORY_CACHE_TTL):
        self._mem_cache[key] = (value, time.time() + ttl)

    def _disk_get(self, key: str):
        fname = self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        if not fname.exists():
            return None
        try:
            with open(fname, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if time.time() > obj.get("ts", 0) + DISK_CACHE_TTL:
                try:
                    fname.unlink()
                except Exception:
                    pass
                return None
            return obj.get("value")
        except Exception:
            return None

    def _disk_set(self, key: str, value):
        fname = self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        try:
            with open(fname, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "value": value}, f)
        except Exception:
            pass

    def get_cached_response(self, key: str):
        v = self._mem_get(key)
        if v is not None:
            return v
        v = self._disk_get(key)
        if v is not None:
            # promote to memory
            self._mem_set(key, v)
        return v

    def set_cached_response(self, key: str, value, mem_ttl: int = MEMORY_CACHE_TTL):
        self._mem_set(key, value, ttl=mem_ttl)
        self._disk_set(key, value)

    # -------------------------
    # Circuit breaker + retry
    # -------------------------
    def _is_cb_open(self) -> bool:
        if self._cb_state == "OPEN":
            assert self._cb_open_until is not None
            if time.time() > self._cb_open_until:
                self._cb_state = "HALF_OPEN"
                return False
            return True
        return False

    def _record_cb_failure(self):
        with self._cb_lock:
            self._cb_failures += 1
            if self._cb_failures >= 3:
                self._cb_state = "OPEN"
                self._cb_open_until = time.time() + 60
                self._log(
                    "warning",
                    status="cb_open",
                    msg="Circuit breaker aberto por falhas repetidas",
                )

    def _record_cb_success(self):
        with self._cb_lock:
            self._cb_failures = 0
            self._cb_state = "CLOSED"
            self._cb_open_until = None

    async def _send_with_retry(
        self, coro_fn, *args, max_retries: int = 3, backoff_base: float = 0.5, **kwargs
    ):
        last_exc = None
        for attempt in range(1, max_retries + 1):
            if self._is_cb_open():
                raise RuntimeError("Circuit breaker aberto")
            try:
                start = time.time()
                res = await coro_fn(*args, **kwargs)
                elapsed = time.time() - start
                self._metrics["calls"] += 1
                self._metrics["success"] += 1
                self._metrics["total_time"] += elapsed
                self._record_cb_success()
                return res
            except Exception as e:
                last_exc = e
                self._metrics["calls"] += 1
                self._metrics["fail"] += 1
                self._record_cb_failure()
                await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))
        raise last_exc

    # -------------------------
    # Public API
    # -------------------------
    def get_metrics(self) -> Dict:
        calls = self._metrics.get("calls", 0)
        avg = (self._metrics.get("total_time", 0.0) / calls) if calls else 0.0
        return {
            "calls": calls,
            "success": self._metrics.get("success", 0),
            "fail": self._metrics.get("fail", 0),
            "avg_time": avg,
        }

    def check_health(self) -> Dict:
        cert_info = self._validate_certificate(self.cert_path)
        can_write = os.access(str(self.backup_dir), os.W_OK)
        return {
            "certificate": cert_info,
            "simulation_mode": self.simulation_mode,
            "backup_writable": can_write,
            "circuit_state": self._cb_state,
        }

    async def enviar_evento_async(
        self, xml_evento: str, lote: Optional[str] = None, cnpj_empresa: str = ""
    ) -> Dict:
        """Envia evento de forma assíncrona com retry, circuito e cache.

        Usa `ServicoESocial.enviar_evento` internamente (simulado).
        """
        # Basic validations
        if not xml_evento or not xml_evento.strip():
            raise ValueError("XML do evento não pode estar vazio")
        size = len(xml_evento.encode("utf-8"))
        if size > MAX_XML_BYTES:
            raise ValueError("XML excede tamanho máximo permitido")

        key = hashlib.sha256(xml_evento.encode()).hexdigest()
        cached = self.get_cached_response(key)
        if cached:
            self._log(
                "info",
                cnpj=cnpj_empresa,
                tipo_evento=lote or "",
                status="cache_hit",
                msg="Resposta retornada do cache",
            )
            return cached

        async def call():
            # run the synchronous envia in thread to keep async API
            return await asyncio.to_thread(self.esocial.enviar_evento, xml_evento, lote)

        res = await self._send_with_retry(call)
        # cache successful responses
        try:
            self.set_cached_response(key, res)
        except Exception:
            pass

        # register evidence & metrics
        self.gerenciador.registrar_evidencia(
            tipo="envio_esocial",
            descricao=f"Envio async - protocolo {res.get('protocolo')}",
            dados={"lote": res.get("lote"), "status": res.get("status")},
        )
        self._log(
            "info",
            cnpj=cnpj_empresa,
            tipo_evento=lote or "",
            status=res.get("status", ""),
            msg="Envio realizado",
        )
        return res

    def enviar_evento(
        self, xml_evento: str, lote: Optional[str] = None, cnpj_empresa: str = ""
    ) -> Dict:
        """Síncrono wrapper que chama `enviar_evento_async` quando necessário."""
        # If an event loop is already running, execute the async call in a
        # dedicated thread which creates its own event loop to avoid
        # RuntimeError("This event loop is already running"). This provides
        # safe cross-thread orchestration without requiring external deps.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():

            def _call_in_thread():
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(
                        self.enviar_evento_async(xml_evento, lote, cnpj_empresa)
                    )
                finally:
                    try:
                        new_loop.close()
                    except Exception:
                        pass

            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_call_in_thread)
                return fut.result()

        # No running loop: safe to run directly
        return asyncio.run(self.enviar_evento_async(xml_evento, lote, cnpj_empresa))

    # -------------------------
    # File generation / backup
    # -------------------------
    def gerar_arquivo_fiscal(
        self,
        tipo: TipoArquivoFiscal,
        dados: Dict,
        periodo: Tuple[datetime, datetime],
        caminho_saida: Optional[str] = None,
    ) -> str:
        # delegate to exportador but enforce size/SPED limits and backup
        exportador = self.exportadores.get(tipo)
        if not exportador:
            raise ValueError(f"Tipo de arquivo não suportado: {tipo}")

        caminho = exportador.gerar_arquivo(dados, periodo, caminho_saida)

        # validate size limits
        size = Path(caminho).stat().st_size
        if tipo == TipoArquivoFiscal.SPED_CONTABIL and size > MAX_SPED_BYTES:
            raise ValueError("Arquivo SPED excede tamanho máximo permitido")

        # backup (async fire-and-forget)
        try:
            asyncio.get_event_loop().run_in_executor(None, self._backup_file, caminho)
        except Exception:
            # may be no running loop; run sync
            self._backup_file(caminho)

        # evidence
        try:
            with open(caminho, "rb") as f:
                hash_arquivo = hashlib.sha256(f.read()).hexdigest()
            self.gerenciador.registrar_evidencia(
                tipo="geracao_arquivo_fiscal",
                descricao=f"Arquivo fiscal gerado: {tipo.value}",
                dados={"tipo_arquivo": tipo.value, "hash_arquivo": hash_arquivo},
                arquivo_relacionado=caminho,
            )
        except Exception:
            pass

        return caminho

    def _backup_file(self, caminho: str):
        try:
            src = Path(caminho)
            if not src.exists():
                return
            dest = self.backup_dir / src.name
            shutil.copy2(src, dest)
            # retention: compress files older than retention_days
            cutoff = time.time() - (self.retention_days * 24 * 3600)
            to_archive = []
            for f in self.backup_dir.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff and f.suffix != ".zip":
                    to_archive.append(f)
            if to_archive:
                zip_name = self.backup_dir / f"archive_{int(time.time())}.zip"
                with zipfile.ZipFile(
                    zip_name, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    for f in to_archive:
                        try:
                            zf.write(f, arcname=f.name)
                            f.unlink()
                        except Exception:
                            continue
        except Exception as e:
            self._log("error", status="backup", msg=str(e))

    def validar_arquivo_fiscal(
        self, tipo: TipoArquivoFiscal, caminho_arquivo: str
    ) -> Dict:
        exportador = self.exportadores.get(tipo)
        if not exportador:
            raise ValueError(f"Tipo de arquivo não suportado: {tipo}")
        return exportador.validar_arquivo(caminho_arquivo)


# Exportações públicas
__all__ = [
    "FiscalService",
    "ServicoESocial",
    "ServicoFGTS",
    "TipoEventoESocial",
    "StatusEnvioESocial",
    "TipoArquivoFiscal",
    "IExportadorFiscal",
    "ExportadorSPED",
    "ExportadorDCTF",
    "ExportadorDIRF",
    "GerenciadorEvidencias",
]
