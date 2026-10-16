"""
Serviço de Ingestão e Extração de Dados
Pipeline robusto para extração de dados de documentos contábeis

Funcionalidades:
- OCR robusto para holerites, contratos, comprovantes
- NER/Parser para extrair CPF, CNPJ, salários, datas, etc.
- Validação automática com heurísticas
- Integração com sistema de evidências legais
- Tratamento de confiança e verificação humana
"""

import hashlib
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Attempt to import the project's evidence manager; if unavailable,
# provide a lightweight mock so the ingest service remains independent.
try:
    from .evidence_service import GerenciadorEvidencias  # type: ignore
except Exception:  # pragma: no cover - fallback

    class GerenciadorEvidencias:  # type: ignore
        class Evidencia:
            def __init__(self, id_evidencia: str):
                self.id_evidencia = id_evidencia

        def __init__(self):
            pass

        def registrar_evidencia(self, *args, **kwargs):
            # Minimal contract used by ingestao_service: return object with id_evidencia
            return GerenciadorEvidencias.Evidencia(
                id_evidencia=f"mock-{int(time.time())}"
            )


# Structured logger for ingestion service
_LOGGER = logging.getLogger("contabil_ingestao")
if not _LOGGER.handlers:
    ch = logging.StreamHandler()
    fmt = (
        "%(asctime)s | %(levelname)s | [%(module)s] | ID_DOC: %(id_doc)s | %(message)s"
    )
    ch.setFormatter(logging.Formatter(fmt))

    # Ensure all records have an 'id_doc' attribute for formatting
    class _DefaultIdFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, "id_doc"):
                record.id_doc = "-"
            return True

    ch.addFilter(_DefaultIdFilter())
    _LOGGER.addHandler(ch)
    _LOGGER.setLevel(logging.INFO)


def _get_adapter(id_doc: Optional[str]):
    return logging.LoggerAdapter(_LOGGER, {"id_doc": id_doc or "-"})


logger = _LOGGER

# Tentativa de importação de dependências opcionais
TESSERACT_AVAILABLE = False
SPACY_AVAILABLE = False
PIL_AVAILABLE = False
PDF2IMAGE_AVAILABLE = False

try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    PIL_AVAILABLE = True
    TESSERACT_AVAILABLE = True
    logger.info("OCR disponível: pytesseract + PIL", extra={"id_doc": "-"})
except Exception as e:  # pragma: no cover - ambiente variável
    logger.warning(f"OCR não disponível: {e}", extra={"id_doc": "-"})

try:
    from pdf2image import convert_from_path  # type: ignore

    PDF2IMAGE_AVAILABLE = True
    logger.info("Conversão PDF disponível: pdf2image", extra={"id_doc": "-"})
except Exception as e:  # pragma: no cover - ambiente variável
    logger.warning(f"pdf2image não disponível: {e}", extra={"id_doc": "-"})

try:
    import spacy  # type: ignore

    SPACY_AVAILABLE = True
    logger.info("NER disponível: spaCy", extra={"id_doc": "-"})
except Exception as e:  # pragma: no cover - ambiente variável
    logger.warning(f"spaCy não disponível: {e}", extra={"id_doc": "-"})


class DataExtractionError(Exception):
    """Exceção customizada para erros de extração de dados"""

    def __init__(
        self,
        message: str,
        confianca: float = 0.0,
        dados_parciais: Optional[Dict] = None,
        requer_verificacao: bool = False,
    ):
        """
        Cria exceção de erro de extração

        Args:
            message: Mensagem de erro
            confianca: Nível de confiança da extração (0.0 a 1.0)
            dados_parciais: Dados extraídos parcialmente (se houver)
            requer_verificacao: Se requer verificação humana
        """
        super().__init__(message)
        self.confianca = confianca
        self.dados_parciais = dados_parciais or {}
        self.requer_verificacao = requer_verificacao


class ValidadorCampos:
    """Validador de campos extraídos com heurísticas"""

    @staticmethod
    def validar_cpf(cpf: str) -> bool:
        """Valida CPF com algoritmo oficial"""
        if not cpf:
            return False

        # Remove caracteres não numéricos
        cpf = re.sub(r"\D", "", cpf)

        if len(cpf) != 11:
            return False

        # Verifica se todos os dígitos são iguais
        if cpf == cpf[0] * 11:
            return False

        # Validação dos dígitos verificadores
        def calcular_digito(cpf_parcial: str) -> int:
            soma = sum(
                int(cpf_parcial[i]) * (len(cpf_parcial) + 1 - i)
                for i in range(len(cpf_parcial))
            )
            resto = soma % 11
            return 0 if resto < 2 else 11 - resto

        # Valida primeiro dígito
        if int(cpf[9]) != calcular_digito(cpf[:9]):
            return False

        # Valida segundo dígito
        if int(cpf[10]) != calcular_digito(cpf[:10]):
            return False

        return True

    @staticmethod
    def validar_cnpj(cnpj: str) -> bool:
        """Valida CNPJ com algoritmo oficial"""
        if not cnpj:
            return False

        # Remove caracteres não numéricos
        cnpj = re.sub(r"\D", "", cnpj)

        if len(cnpj) != 14:
            return False

        # Verifica se todos os dígitos são iguais
        if cnpj == cnpj[0] * 14:
            return False

        # Validação dos dígitos verificadores
        def calcular_digito(cnpj_parcial: str, pesos: List[int]) -> int:
            soma = sum(int(cnpj_parcial[i]) * pesos[i] for i in range(len(pesos)))
            resto = soma % 11
            return 0 if resto < 2 else 11 - resto

        # Primeiro dígito
        pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if int(cnpj[12]) != calcular_digito(cnpj[:12], pesos1):
            return False

        # Segundo dígito
        pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if int(cnpj[13]) != calcular_digito(cnpj[:13], pesos2):
            return False

        return True

    @staticmethod
    def validar_data(data_str: str) -> Optional[datetime]:
        """Valida e converte string de data para datetime"""
        formatos = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%d/%m/%y",
            "%d.%m.%Y",
        ]

        for formato in formatos:
            try:
                return datetime.strptime(data_str, formato)
            except ValueError:
                continue

        return None

    @staticmethod
    def validar_valor_monetario(valor: Decimal) -> bool:
        """Valida se valor monetário está em faixa razoável"""
        # Salário mínimo: ~1500, Máximo razoável: 1 milhão
        return Decimal("100") <= valor <= Decimal("1000000")


class ExtractorOCR:
    """Extrator de texto usando OCR"""

    def __init__(self, tesseract_cmd: Optional[str] = None):
        """
        Inicializa extrator OCR

        Args:
            tesseract_cmd: Caminho customizado para executável tesseract
        """
        if not TESSERACT_AVAILABLE or not PIL_AVAILABLE:
            raise RuntimeError(
                "OCR não disponível. Instale: pip install pytesseract pillow"
            )

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        self.config_ocr = "--oem 3 --psm 6 -l por"  # Português, layout em bloco

    def extrair_texto_imagem(self, caminho_imagem: str) -> Tuple[str, float]:
        """
        Extrai texto de imagem usando OCR

        Args:
            caminho_imagem: Caminho da imagem

        Returns:
            Tupla (texto_extraido, confianca)
        """
        try:
            imagem = Image.open(caminho_imagem)

            # OCR com configuração otimizada para português
            texto = pytesseract.image_to_string(imagem, config=self.config_ocr)

            # Calcula confiança baseada em dados de OCR
            dados_ocr = pytesseract.image_to_data(
                imagem, output_type=pytesseract.Output.DICT, config=self.config_ocr
            )

            # Confiança média (ignora valores -1)
            confiancias = [int(c) for c in dados_ocr.get("con", []) if int(c) > 0]
            confianca = (
                sum(confiancias) / len(confiancias) / 100 if confiancias else 0.0
            )

            logger.info(
                f"OCR concluído: {len(texto)} caracteres, confiança {confianca:.2%}"
            )

            return texto, confianca

        except Exception as e:
            logger.error(f"Erro no OCR: {e}")
            raise DataExtractionError(
                f"Falha no OCR: {e}", confianca=0.0, requer_verificacao=True
            )

    def extrair_texto_pdf(self, caminho_pdf: str) -> Tuple[str, float]:
        """
        Extrai texto de PDF (converte para imagens e faz OCR)

        Args:
            caminho_pdf: Caminho do PDF

        Returns:
            Tupla (texto_extraido, confianca_media)
        """
        if not PDF2IMAGE_AVAILABLE:
            raise RuntimeError(
                "Conversão PDF não disponível. Instale: pip install pdf2image"
            )

        try:
            # Converte PDF para imagens
            imagens = convert_from_path(caminho_pdf, dpi=300)

            textos = []
            confiancias = []

            for i, imagem in enumerate(imagens):
                logger.debug(f"Processando página {i + 1}/{len(imagens)}")

                # OCR em cada página
                texto = pytesseract.image_to_string(imagem, config=self.config_ocr)
                dados_ocr = pytesseract.image_to_data(
                    imagem, output_type=pytesseract.Output.DICT, config=self.config_ocr
                )

                textos.append(texto)

                # Confiança da página
                conf_pagina = [int(c) for c in dados_ocr.get("con", []) if int(c) > 0]
                if conf_pagina:
                    confiancias.append(sum(conf_pagina) / len(conf_pagina) / 100)

            texto_completo = "\n\n".join(textos)
            confianca_media = (
                sum(confiancias) / len(confiancias) if confiancias else 0.0
            )

            logger.info(
                f"OCR PDF concluído: {len(imagens)} páginas, "
                f"{len(texto_completo)} caracteres, confiança {confianca_media:.2%}"
            )

            return texto_completo, confianca_media

        except Exception as e:
            logger.error(f"Erro ao processar PDF: {e}")
            raise DataExtractionError(
                f"Falha ao processar PDF: {e}", confianca=0.0, requer_verificacao=True
            )


class BaseParser:
    """Interface mínima para parser plugins.

    Implementar `applies_to(text: str) -> bool` e `parse(text: str) -> Dict`.
    """

    def applies_to(self, text: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError()

    def parse(self, text: str) -> Dict:  # pragma: no cover - interface
        raise NotImplementedError()

    pass


class ParserDocumentos:
    """Parser para extrair campos estruturados de documentos contábeis

    Agora suporta plugins: novos parsers podem ser registrados sem alterar
    o núcleo do `IngestaoService`.
    """

    def __init__(
        self, usar_spacy: bool = False, plugins: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa parser

        Args:
            usar_spacy: Se deve usar spaCy para NER (requer modelo treinado)
        """
        self.usar_spacy = usar_spacy and SPACY_AVAILABLE
        self.nlp = None
        self._plugins: Dict[str, Any] = plugins or {}

        if self.usar_spacy:
            try:
                self.nlp = spacy.load("pt_core_news_sm")
                logger.info("SpaCy carregado para NER")
            except Exception as e:
                logger.warning("Não foi possível carregar spaCy: %s", e)
                self.usar_spacy = False

    def register_plugin(self, name: str, plugin_instance: Any) -> None:
        """Registra um parser plugin para um tipo de documento específico."""
        self._plugins[name] = plugin_instance
        logger.info("Plugin registrado: %s", name)

    def get_plugin(self, name: str) -> Optional[Any]:
        return self._plugins.get(name)

    def extrair_campos(self, texto: str) -> Dict:
        """
        Extrai campos estruturados do texto

        Args:
            texto: Texto extraído do documento

        Returns:
            Dicionário com campos extraídos
        """
        # Se houver plugin específico aplicável, use-o
        # (ex.: plugin para nota fiscal que extrai campos específicos)
        # Os plugins retornam um dicionário similar ao retorno padrão.
        campos = {}

        # Plugins têm prioridade: iteram sobre registros e aplicam transformações
        for plugin_name, plugin in self._plugins.items():
            try:
                if hasattr(plugin, "applies_to") and plugin.applies_to(texto):
                    logger.info("Aplicando plugin %s para extração", plugin_name)
                    plugin_campos = plugin.parse(texto)
                    if isinstance(plugin_campos, dict):
                        campos.update(plugin_campos)
            except Exception as e:
                logger.warning("Falha no plugin %s: %s", plugin_name, e)

        # Extração padrão (básica) complementa o que faltou
        default_campos = {
            "cp": self._extrair_cpf(texto),
            "cnpj": self._extrair_cnpj(texto),
            "nome": self._extrair_nome(texto),
            "salario_base": self._extrair_salario(texto),
            "datas": self._extrair_datas(texto),
            "valores_monetarios": self._extrair_valores_monetarios(texto),
            "cargo": self._extrair_cargo(texto),
            "empresa": self._extrair_empresa(texto),
        }

        # Preenche com campos padrão sem sobrescrever os extraídos por plugins
        for k, v in default_campos.items():
            if k not in campos and v is not None:
                campos[k] = v

        # Remove campos vazios
        campos = {k: v for k, v in campos.items() if v is not None}

        return campos

    def _extrair_cpf(self, texto: str) -> Optional[str]:
        """Extrai CPF do texto"""
        # Padrões: 123.456.789-10 ou 12345678910
        padroes = [
            r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
        ]

        for padrao in padroes:
            matches = re.findall(padrao, texto)
            for match in matches:
                cpf_limpo = re.sub(r"\D", "", match)
                if ValidadorCampos.validar_cpf(cpf_limpo):
                    return cpf_limpo

        return None

    def _extrair_cnpj(self, texto: str) -> Optional[str]:
        """Extrai CNPJ do texto"""
        # Padrões: 12.345.678/0001-90 ou 12345678000190
        padroes = [
            r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
        ]

        for padrao in padroes:
            matches = re.findall(padrao, texto)
            for match in matches:
                cnpj_limpo = re.sub(r"\D", "", match)
                if ValidadorCampos.validar_cnpj(cnpj_limpo):
                    return cnpj_limpo

        return None

    def _extrair_nome(self, texto: str) -> Optional[str]:
        """Extrai nome de pessoa do texto"""
        if self.usar_spacy and self.nlp:
            doc = self.nlp(texto)
            # Busca entidades do tipo PERSON
            nomes = [ent.text for ent in doc.ents if ent.label_ == "PER"]
            if nomes:
                return nomes[0]  # Retorna primeiro nome encontrado

        # Fallback: regex para padrão de nome
        # Procura por "Nome:" ou "Funcionário:" seguido de nome
        padroes = [
            r"(?:Nome|Funcionário|Funcionario|Empregado):\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)+)",
            r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+\s+(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+\s+)*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)\b",
        ]

        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                nome = match.group(1) if ":" in padrao else match.group(0)
                # Valida se tem pelo menos 2 palavras de 3+ letras
                palavras = nome.split()
                if len(palavras) >= 2 and all(len(p) >= 3 for p in palavras):
                    return nome

        return None

    def _extrair_salario(self, texto: str) -> Optional[Decimal]:
        """Extrai salário base do texto"""
        # Procura por padrões: "Salário: R$ 1.234,56" ou "Salário Base: 1234.56"
        padroes = [
            r"(?:Salário|Salario)\s*(?:Base)?:\s*R?\$?\s*([\d\.]+,\d{2})",
            r"(?:Salário|Salario)\s*(?:Base)?:\s*R?\$?\s*([\d,]+\.\d{2})",
        ]

        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                valor_str = match.group(1)
                # Converte para Decimal
                valor_str = valor_str.replace(".", "").replace(",", ".")
                try:
                    valor = Decimal(valor_str)
                    if ValidadorCampos.validar_valor_monetario(valor):
                        return valor
                except InvalidOperation:
                    continue

        return None

    def _extrair_datas(self, texto: str) -> List[str]:
        """Extrai datas do texto"""
        # Padrões de data: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD
        padrao = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
        matches = re.findall(padrao, texto)

        datas_validadas = []
        for match in matches:
            data = ValidadorCampos.validar_data(match)
            if data:
                datas_validadas.append(data.strftime("%Y-%m-%d"))

        return datas_validadas

    def _extrair_valores_monetarios(self, texto: str) -> List[Decimal]:
        """Extrai todos os valores monetários do texto"""
        # Padrões: R$ 1.234,56 ou 1234.56
        padroes = [
            r"R\$\s*([\d\.]+,\d{2})",
            r"\b([\d\.]+,\d{2})\b",
        ]

        valores = []
        for padrao in padroes:
            matches = re.findall(padrao, texto)
            for match in matches:
                valor_str = match.replace(".", "").replace(",", ".")
                try:
                    valor = Decimal(valor_str)
                    if Decimal("0") < valor <= Decimal("1000000"):
                        valores.append(valor)
                except InvalidOperation:
                    continue

        # Remove duplicatas mantendo ordem
        valores_unicos = []
        for v in valores:
            if v not in valores_unicos:
                valores_unicos.append(v)

        return valores_unicos

    def _extrair_cargo(self, texto: str) -> Optional[str]:
        """Extrai cargo/função do texto"""
        padroes = [
            r"(?:Cargo|Função|Funcao):\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç\s]+)",
        ]

        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                cargo = match.group(1).strip()
                # Limita tamanho e valida
                if 3 <= len(cargo) <= 50:
                    return cargo

        return None

    def _extrair_empresa(self, texto: str) -> Optional[str]:
        """Extrai nome da empresa do texto"""
        padroes = [
            r"(?:Empresa|Empregador|Razão Social|Razao Social):\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç\s&\-]+)",
        ]

        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                empresa = match.group(1).strip()
                if 3 <= len(empresa) <= 100:
                    return empresa

        return None


class IngestaoService:
    """
    Serviço principal de ingestão e extração de dados
    Pipeline completo: OCR → Parser → Validação → Evidências
    """

    _instance_lock = threading.Lock()
    _instance: Optional["IngestaoService"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._instance_lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
        limiar_confianca: float = None,
        usar_spacy: Optional[bool] = None,
        cache_resultados: Optional[bool] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Inicializa serviço de ingestão

        Args:
            gerenciador_evidencias: Gerenciador de evidências (cria novo se None)
            limiar_confianca: Limiar mínimo de confiança para aceitar extração
            usar_spacy: Se deve usar spaCy para NER avançado
            cache_resultados: Se deve fazer cache de resultados de extração
        """
        # Singletons safe init pattern: only initialize once
        if hasattr(self, "_initialized") and self._initialized:
            return

        # Load default config and allow env or direct overrides
        defaults = {
            "limiar_confianca": 0.7,
            "usar_spacy": False,
            "cache_resultados": True,
            "ocr_retry_attempts": 3,
            "ocr_retry_backof": 0.5,
            "ocr_failure_threshold": 5,
        }
        if default_config:
            defaults.update(default_config)

        # environment overrides
        defaults["limiar_confianca"] = float(
            os.getenv("INGESTAO_LIMIAR_CONFIANCA", defaults["limiar_confianca"])
        )
        defaults["usar_spacy"] = os.getenv(
            "INGESTAO_USAR_SPACY", str(defaults["usar_spacy"])
        ).lower() in ("1", "true", "yes")
        defaults["cache_resultados"] = os.getenv(
            "INGESTAO_CACHE", str(defaults["cache_resultados"])
        ).lower() in ("1", "true", "yes")

        self._lock = threading.RLock()
        self.gerenciador_evidencias = gerenciador_evidencias or GerenciadorEvidencias()
        self.limiar_confianca = (
            max(0.0, min(1.0, limiar_confianca))
            if limiar_confianca is not None
            else defaults["limiar_confianca"]
        )
        self.usar_spacy = (
            usar_spacy if usar_spacy is not None else defaults["usar_spacy"]
        )
        self.cache_resultados = (
            cache_resultados
            if cache_resultados is not None
            else defaults["cache_resultados"]
        )
        self._cache: Dict[str, Dict] = {} if self.cache_resultados else None

        # OCR resilience settings
        self._ocr_retry_attempts = int(defaults["ocr_retry_attempts"])
        self._ocr_retry_backoff = float(defaults["ocr_retry_backof"])
        self._ocr_failure_threshold = int(defaults["ocr_failure_threshold"])
        self._ocr_failure_count = 0
        self._circuit_state = "CLOSED"  # CLOSED, OPEN, DEGRADED

        # Inicializa componentes do pipeline
        self.ocr = None
        if TESSERACT_AVAILABLE and PIL_AVAILABLE:
            try:
                self.ocr = ExtractorOCR()
            except RuntimeError:
                logger.warning("OCR não disponível neste sistema")

        self.parser = ParserDocumentos(usar_spacy=self.usar_spacy)

        # Marca como inicializado (evita reinit em chamadas subsequentes)
        self._initialized = True

        logger.info(
            f"IngestaoService inicializado - Limiar confiança: {self.limiar_confianca * 100:.0f}%",
        )

        # Default temp dir (verificado no healthcheck)
        self._temp_dir = tempfile.gettempdir()

    def processar_documento(
        self, caminho_arquivo: str, tipo_documento: str = "desconhecido"
    ) -> Dict:
        """
        Processa documento completo: OCR + Extração + Validação + Evidências

        Args:
            caminho_arquivo: Caminho do arquivo (imagem ou PDF)
            tipo_documento: Tipo do documento (holerite, contrato, etc.)

        Returns:
            Dict com dados extraídos e metadados

        Raises:
            DataExtractionError: Se extração falhar ou confiança for baixa
        """
        caminho = Path(caminho_arquivo)

        if not caminho.exists():
            raise DataExtractionError(
                f"Arquivo não encontrado: {caminho_arquivo}",
                confianca=0.0,
                requer_verificacao=False,
            )

        # Verifica cache (thread-safe)
        if self.cache_resultados and self._cache is not None:
            cache_key = self._calcular_hash_arquivo(caminho_arquivo)
            with self._lock:
                if cache_key in self._cache:
                    logger.info("Resultado em cache para: %s", caminho.name)
                    return self._cache[cache_key]

        logger.info(f"Iniciando processamento: {caminho.name}")

        # Etapa 1: Calcular hash do documento original
        hash_documento = self._calcular_hash_arquivo(caminho_arquivo)

        # Etapa 2: OCR - Extrair texto
        texto, confianca_ocr = self._executar_ocr(caminho_arquivo)

        if confianca_ocr < self.limiar_confianca:
            logger.warning(
                f"Confiança OCR baixa: {confianca_ocr:.2%} (limiar: {self.limiar_confianca:.2%})"
            )

        # Etapa 3: Parser - Extrair campos estruturados
        campos_extraidos = self.parser.extrair_campos(texto)

        # Etapa 4: Validação
        validacao = self._validar_campos(campos_extraidos)

        # Calcula confiança final (média entre OCR e validação)
        confianca_final = (confianca_ocr + validacao["score"]) / 2

        # Etapa 5: Decidir se aceita ou requer verificação
        requer_verificacao = confianca_final < self.limiar_confianca

        if requer_verificacao:
            logger.warning(
                f"Extração requer verificação humana - Confiança: {confianca_final:.2%}"
            )

        # Etapa 6: Montar resultado
        resultado = {
            "arquivo": str(caminho.absolute()),
            "tipo_documento": tipo_documento,
            "hash_documento": hash_documento,
            "timestamp": datetime.now().isoformat(),
            "texto_extraido": texto,
            "campos": campos_extraidos,
            "confianca": {
                "ocr": confianca_ocr,
                "validacao": validacao["score"],
                "final": confianca_final,
            },
            "validacao": validacao,
            "requer_verificacao": requer_verificacao,
        }

        # Etapa 7: Registrar evidência
        try:
            evidencia = self.gerenciador_evidencias.registrar_evidencia(
                tipo="extracao_dados",
                descricao=f"Extração de dados: {tipo_documento}",
                dados={
                    "tipo_documento": tipo_documento,
                    "campos_extraidos": campos_extraidos,
                    "confianca_final": float(confianca_final),
                    "requer_verificacao": requer_verificacao,
                },
                arquivo_relacionado=caminho_arquivo,
            )

            resultado["id_evidencia"] = evidencia.id_evidencia

            logger.info(
                f"Evidência registrada: {evidencia.id_evidencia} - "
                f"Confiança: {confianca_final:.2%}"
            )

        except Exception as e:
            logger.error(f"Erro ao registrar evidência: {e}")
            # Continua mesmo com erro de evidência

        # Adiciona ao cache (thread-safe)
        if self.cache_resultados and self._cache is not None:
            with self._lock:
                self._cache[hash_documento] = resultado

        # Etapa 8: Lançar exceção se confiança muito baixa
        if confianca_final < 0.5:  # Confiança crítica
            raise DataExtractionError(
                f"Confiança muito baixa: {confianca_final:.2%}",
                confianca=confianca_final,
                dados_parciais=resultado,
                requer_verificacao=True,
            )

        return resultado

    def _executar_ocr(self, caminho_arquivo: str) -> Tuple[str, float]:
        """Executa OCR no arquivo"""
        # If circuit is in DEGRADED mode, avoid heavy OCR calls.
        caminho = Path(caminho_arquivo)
        extensao = caminho.suffix.lower()

        if self._circuit_state == "DEGRADED":
            # In degraded mode we skip OCR and rely on available text (none)
            # and fall back to regex-based extraction to avoid timeouts.
            logger.warning(
                "OCR in degraded mode, skipping OCR call",
                extra={"id_doc": caminho.name},
            )
            return "", 0.0

        if not self.ocr:
            raise DataExtractionError(
                "OCR não disponível. Instale: pip install pytesseract pillow",
                confianca=0.0,
                requer_verificacao=True,
            )

        # Retry with exponential backoff for transient IO/ocr errors
        attempts = max(1, int(self._ocr_retry_attempts))
        backoff_base = float(self._ocr_retry_backoff)

        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                if extensao in [".jpg", ".jpeg", ".png", ".bmp", ".tif"]:
                    texto, confianca = self.ocr.extrair_texto_imagem(caminho_arquivo)
                elif extensao == ".pd":
                    texto, confianca = self.ocr.extrair_texto_pdf(caminho_arquivo)
                else:
                    raise DataExtractionError(
                        f"Formato não suportado: {extensao}",
                        confianca=0.0,
                        requer_verificacao=False,
                    )

                # Success: reset failure count and possibly close circuit
                self._ocr_failure_count = 0
                if self._circuit_state in ("OPEN", "DEGRADED"):
                    self._circuit_state = "CLOSED"
                    logger.info(
                        "Circuit breaker closed after successful OCR",
                        extra={"id_doc": caminho.name},
                    )

                return texto, confianca

            except DataExtractionError as e:
                last_err = e
                # DataExtractionError signals OCR-level failure; count it
                self._ocr_failure_count += 1
                logger.warning(
                    f"OCR attempt {attempt}/{attempts} failed: {e}",
                    extra={"id_doc": caminho.name},
                )
                # If reached failure threshold, enter degraded mode
                if self._ocr_failure_count >= self._ocr_failure_threshold:
                    self._circuit_state = "DEGRADED"
                    logger.error(
                        "Circuit breaker entered DEGRADED mode due to repeated OCR failures",
                        extra={"id_doc": caminho.name},
                    )
                    break
                # Backoff before retrying
                time.sleep(backoff_base * (2 ** (attempt - 1)))

            except Exception as e:
                last_err = e
                self._ocr_failure_count += 1
                logger.error(
                    f"Unexpected OCR error on attempt {attempt}: {e}",
                    extra={"id_doc": caminho.name},
                )
                if self._ocr_failure_count >= self._ocr_failure_threshold:
                    self._circuit_state = "DEGRADED"
                    logger.error(
                        "Circuit breaker entered DEGRADED mode due to repeated unexpected errors",
                        extra={"id_doc": caminho.name},
                    )
                    break
                time.sleep(backoff_base * (2 ** (attempt - 1)))

        # If we exit loop without successful extraction, raise last error if present
        if last_err:
            raise DataExtractionError(
                str(last_err), confianca=0.0, requer_verificacao=True
            )

        # Fallback generic error
        raise DataExtractionError(
            "Falha desconhecida no OCR", confianca=0.0, requer_verificacao=True
        )

    # ---------- Infrastructure / Extensibility APIs ----------
    def check_health(self) -> Dict[str, Any]:
        """Verifica dependências essenciais em tempo de execução.

        Retorna dict com chaves: tesseract, spacy_model, tempdir_writable
        """
        status = {
            "tesseract": {"available": False, "detail": None},
            "spacy_model": {"loaded": False, "detail": None},
            "tempdir_writable": {"writable": False, "path": self._temp_dir},
        }

        # Checa Tesseract binário
        try:
            if TESSERACT_AVAILABLE:
                ver = pytesseract.get_tesseract_version()
                status["tesseract"]["available"] = True
                status["tesseract"]["detail"] = str(ver)
            else:
                # tenta localizar binário no PATH
                tpath = shutil.which("tesseract")
                if tpath:
                    status["tesseract"]["available"] = True
                    status["tesseract"]["detail"] = tpath
                else:
                    status["tesseract"]["detail"] = "tesseract binary not found"
        except Exception as e:
            status["tesseract"]["detail"] = str(e)

        # Checa spaCy model carregado
        try:
            if SPACY_AVAILABLE and getattr(self.parser, "nlp", None):
                status["spacy_model"]["loaded"] = True
                status["spacy_model"]["detail"] = getattr(self.parser.nlp, "meta", {})
            else:
                status["spacy_model"]["detail"] = "spaCy not loaded"
        except Exception as e:
            status["spacy_model"]["detail"] = str(e)

        # Checa permissão de escrita em temp dir
        try:
            test_file = Path(self._temp_dir) / f"ingestao_health_{os.getpid()}"
            with open(test_file, "w") as f:
                f.write("ok")
            test_file.unlink(missing_ok=True)
            status["tempdir_writable"]["writable"] = True
        except Exception as e:
            status["tempdir_writable"]["detail"] = str(e)

        # Check for poppler (pdftoppm) if pdf2image is expected
        try:
            poppler_bin = shutil.which("pdftoppm")
            status["poppler"] = {"available": bool(poppler_bin), "detail": poppler_bin}
        except Exception as e:
            status["poppler"] = {"available": False, "detail": str(e)}

        logger.info("Health check: %s", status)
        return status

    def carregar_modelo_personalizado(self, caminho: str, tipo: str = "spacy") -> bool:
        """Carrega/alternar modelo em tempo de execução.

        - tipo='spacy': `caminho` pode ser nome de modelo ou caminho para diretório do modelo spaCy
        - tipo='ocr': `caminho` pode ser caminho para binário do tesseract ou código de idioma ('por')

        Retorna True se alterado com sucesso.
        """
        try:
            if tipo == "spacy":
                if not SPACY_AVAILABLE:
                    raise RuntimeError("spaCy não está instalado")
                # Tenta carregar modelo especificado
                nlp = spacy.load(caminho)
                self.parser.nlp = nlp
                self.parser.usar_spacy = True
                logger.info("Modelo spaCy carregado dinamicamente: %s", caminho)
                return True

            if tipo == "ocr":
                # Se caminho é um arquivo executável, atualiza o comando do tesseract
                if Path(caminho).exists():
                    self.ocr = ExtractorOCR(tesseract_cmd=caminho)
                    logger.info("Tesseract customizado carregado: %s", caminho)
                    return True
                else:
                    # pode ser um código de idioma, atualiza config de OCR
                    if self.ocr:
                        self.ocr.config_ocr = f"--oem 3 --psm 6 -l {caminho}"
                        logger.info("Idioma OCR atualizado para: %s", caminho)
                        return True
                    raise RuntimeError("OCR não inicializado para aplicar idioma")

            logger.warning("Tipo de modelo desconhecido: %s", tipo)
            return False
        except Exception as e:
            logger.error("Falha ao carregar modelo personalizado (%s): %s", tipo, e)
            return False

    # Plugin API para parsers
    def register_parser_plugin(self, name: str, plugin_instance: Any) -> None:
        with self._lock:
            self.parser.register_plugin(name, plugin_instance)

    def list_parser_plugins(self) -> List[str]:
        return list(getattr(self.parser, "_plugins", {}).keys())

    def _validar_campos(self, campos: Dict) -> Dict:
        """Valida campos extraídos e calcula score de confiança"""
        validacao = {
            "campos_validos": [],
            "campos_invalidos": [],
            "avisos": [],
            "score": 0.0,
        }

        total_campos = len(campos)
        campos_validos = 0

        # Valida CPF
        if "cp" in campos:
            if ValidadorCampos.validar_cpf(campos["cp"]):
                validacao["campos_validos"].append("cp")
                campos_validos += 1
            else:
                validacao["campos_invalidos"].append("cp")
                validacao["avisos"].append("CPF com formato inválido")

        # Valida CNPJ
        if "cnpj" in campos:
            if ValidadorCampos.validar_cnpj(campos["cnpj"]):
                validacao["campos_validos"].append("cnpj")
                campos_validos += 1
            else:
                validacao["campos_invalidos"].append("cnpj")
                validacao["avisos"].append("CNPJ com formato inválido")

        # Valida salário
        if "salario_base" in campos:
            if ValidadorCampos.validar_valor_monetario(campos["salario_base"]):
                validacao["campos_validos"].append("salario_base")
                campos_validos += 1
            else:
                validacao["campos_invalidos"].append("salario_base")
                validacao["avisos"].append("Salário fora da faixa esperada")

        # Valida datas
        if "datas" in campos and campos["datas"]:
            validacao["campos_validos"].append("datas")
            campos_validos += 1

        # Outros campos (validação básica de presença)
        for campo in ["nome", "cargo", "empresa"]:
            if campo in campos and campos[campo]:
                validacao["campos_validos"].append(campo)
                campos_validos += 1

        # Calcula score (0.0 a 1.0)
        if total_campos > 0:
            validacao["score"] = campos_validos / total_campos
        else:
            validacao["score"] = 0.0
            validacao["avisos"].append("Nenhum campo extraído")

        return validacao

    def _calcular_hash_arquivo(self, caminho_arquivo: str) -> str:
        """Calcula hash SHA-256 do arquivo"""
        sha256_hash = hashlib.sha256()
        with open(caminho_arquivo, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def extrair_holerite(self, caminho_arquivo: str) -> Dict:
        """
        Extração especializada para holerite

        Args:
            caminho_arquivo: Caminho do holerite

        Returns:
            Dict com dados do holerite
        """
        resultado = self.processar_documento(caminho_arquivo, tipo_documento="holerite")

        # Pós-processamento específico para holerite
        campos = resultado.get("campos", {})

        holerite = {
            "cp": campos.get("cp"),
            "nome": campos.get("nome"),
            "salario_base": campos.get("salario_base"),
            "cargo": campos.get("cargo"),
            "empresa": campos.get("empresa"),
            "valores": campos.get("valores_monetarios", []),
            "datas": campos.get("datas", []),
            "confianca": resultado["confianca"]["final"],
            "requer_verificacao": resultado["requer_verificacao"],
        }

        return holerite

    def extrair_contrato(self, caminho_arquivo: str) -> Dict:
        """
        Extração especializada para contrato

        Args:
            caminho_arquivo: Caminho do contrato

        Returns:
            Dict com dados do contrato
        """
        resultado = self.processar_documento(caminho_arquivo, tipo_documento="contrato")

        # Pós-processamento específico para contrato
        campos = resultado.get("campos", {})

        contrato = {
            "cp": campos.get("cp"),
            "cnpj": campos.get("cnpj"),
            "nome_funcionario": campos.get("nome"),
            "empresa": campos.get("empresa"),
            "cargo": campos.get("cargo"),
            "salario": campos.get("salario_base"),
            "datas": campos.get("datas", []),
            "confianca": resultado["confianca"]["final"],
            "requer_verificacao": resultado["requer_verificacao"],
        }

        return contrato

    def limpar_cache(self) -> int:
        """
        Limpa o cache de resultados

        Returns:
            Número de itens removidos do cache
        """
        if not self.cache_resultados or self._cache is None:
            return 0

        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache limpo: {count} itens removidos")
        return count

    def obter_estatisticas_cache(self) -> Dict:
        """
        Retorna estatísticas do cache

        Returns:
            Dict com estatísticas do cache
        """
        if not self.cache_resultados or self._cache is None:
            return {"habilitado": False, "itens": 0}

        return {
            "habilitado": True,
            "itens": len(self._cache),
            "chaves": list(self._cache.keys()),
        }

    def validar_lote(
        self, caminhos_arquivos: List[str], continuar_em_erro: bool = True
    ) -> Dict:
        """
        Valida múltiplos arquivos sem processá-los completamente

        Args:
            caminhos_arquivos: Lista de caminhos de arquivos
            continuar_em_erro: Se deve continuar mesmo com erros

        Returns:
            Dict com estatísticas de validação
        """
        resultado = {
            "total": len(caminhos_arquivos),
            "validos": 0,
            "invalidos": 0,
            "erros": [],
        }

        for caminho in caminhos_arquivos:
            try:
                path = Path(caminho)
                if not path.exists():
                    resultado["invalidos"] += 1
                    resultado["erros"].append(
                        {"arquivo": caminho, "erro": "Arquivo não encontrado"}
                    )
                    if not continuar_em_erro:
                        break
                    continue

                ext = path.suffix.lower()
                if ext not in [".jpg", ".jpeg", ".png", ".pd", ".bmp", ".tif"]:
                    resultado["invalidos"] += 1
                    resultado["erros"].append(
                        {"arquivo": caminho, "erro": f"Formato não suportado: {ext}"}
                    )
                    if not continuar_em_erro:
                        break
                    continue

                resultado["validos"] += 1

            except Exception as e:
                resultado["invalidos"] += 1
                resultado["erros"].append({"arquivo": caminho, "erro": str(e)})
                if not continuar_em_erro:
                    break

        logger.info(
            f"Validação de lote: {resultado['validos']}/{resultado['total']} válidos"
        )
        return resultado

    def processar_lote(
        self,
        caminhos_arquivos: List[str],
        tipo_documento: str = "desconhecido",
        continuar_em_erro: bool = True,
    ) -> Dict:
        """
        Processa múltiplos documentos em lote

        Args:
            caminhos_arquivos: Lista de caminhos de arquivos
            tipo_documento: Tipo padrão dos documentos
            continuar_em_erro: Se deve continuar mesmo com erros

        Returns:
            Dict com resultados do processamento em lote
        """
        resultado = {
            "total": len(caminhos_arquivos),
            "processados": 0,
            "erros": 0,
            "com_verificacao": 0,
            "resultados": [],
            "erros_detalhados": [],
        }

        for i, caminho in enumerate(caminhos_arquivos, 1):
            logger.info(
                f"Processando {i}/{len(caminhos_arquivos)}: {Path(caminho).name}"
            )

            try:
                res = self.processar_documento(caminho, tipo_documento)
                resultado["processados"] += 1
                if res.get("requer_verificacao"):
                    resultado["com_verificacao"] += 1
                resultado["resultados"].append(
                    {
                        "arquivo": caminho,
                        "sucesso": True,
                        "confianca": res["confianca"]["final"],
                        "campos": list(res.get("campos", {}).keys()),
                    }
                )

            except DataExtractionError as e:
                resultado["erros"] += 1
                resultado["erros_detalhados"].append(
                    {
                        "arquivo": caminho,
                        "erro": str(e),
                        "confianca": e.confianca,
                        "dados_parciais": bool(e.dados_parciais),
                    }
                )
                if not continuar_em_erro:
                    break

            except Exception as e:
                resultado["erros"] += 1
                resultado["erros_detalhados"].append(
                    {"arquivo": caminho, "erro": str(e), "tipo": type(e).__name__}
                )
                if not continuar_em_erro:
                    break

        logger.info(
            f"Lote concluído: {resultado['processados']}/{resultado['total']} "
            f"processados, {resultado['erros']} erros"
        )
        return resultado
