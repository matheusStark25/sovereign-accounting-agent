"""
Serviço de Integrações Bancárias e Financeiras
Gerencia PIX, Boletos, Pagamentos e Conciliação

Funcionalidades:
- Geração de PIX (QR Code e Copia e Cola)
- Geração de Boletos bancários
- Processamento de pagamentos
- Conciliação bancária automática
- Integração com APIs bancárias (Banco do Brasil, Itaú, Santander, etc.)
- Segurança: Chaves de API via variáveis de ambiente (os.getenv)
"""

import base64
import hashlib
import logging
import os
import re
import uuid
import sys
import asyncio
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple


# Local stub for GerenciadorEvidencias to guarantee standalone operation
class GerenciadorEvidencias:  # type: ignore
    def __init__(self, *args, **kwargs):
        pass

    def registrar_evidencia(self, *args, **kwargs):
        return None


logger = logging.getLogger(__name__)
# Ensure a default StreamHandler to stdout if no handlers are configured
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)


# ============================================================================
# ENUMS E CONSTANTES
# ============================================================================


class TipoPagamento(Enum):
    """Tipos de pagamento"""

    PIX = "pix"
    BOLETO = "boleto"
    TED = "ted"
    DOC = "doc"
    TRANSFERENCIA = "transferencia"


class StatusPagamento(Enum):
    """Status de pagamento"""

    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"
    CANCELADO = "cancelado"
    CONCLUIDO = "concluido"


class TipoChavePix(Enum):
    """Tipos de chave PIX"""

    CPF = "cp"
    CNPJ = "cnpj"
    EMAIL = "email"
    TELEFONE = "telefone"
    ALEATORIA = "aleatoria"


class BancoSuportado(Enum):
    """Bancos com integração suportada"""

    BANCO_DO_BRASIL = "001"
    BRADESCO = "237"
    ITAU = "341"
    SANTANDER = "033"
    CAIXA = "104"
    INTER = "077"
    NUBANK = "260"


# Limites PIX
PIX_VALOR_MINIMO = Decimal("0.01")
PIX_VALOR_MAXIMO = Decimal("1000000.00")  # 1 milhão
PIX_DESCRICAO_MAX_CHARS = 140

# Limites Boleto
BOLETO_VALOR_MINIMO = Decimal("2.50")
BOLETO_VALOR_MAXIMO = Decimal("99999999.99")


# ============================================================================
# FUNÇÕES DE VALIDAÇÃO
# ============================================================================


def validar_cpf(cpf: str) -> bool:
    """Valida CPF usando algoritmo oficial"""
    cpf = re.sub(r"[^0-9]", "", cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    def calcular_digito(cpf_parcial: str, peso_inicial: int) -> str:
        soma = sum(int(d) * p for d, p in zip(cpf_parcial, range(peso_inicial, 1, -1)))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    return cpf[-2:] == calcular_digito(cpf[:9], 10) + calcular_digito(cpf[:10], 11)


def validar_cnpj(cnpj: str) -> bool:
    """Valida CNPJ usando algoritmo oficial"""
    cnpj = re.sub(r"[^0-9]", "", cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    def calcular_digito(cnpj_parcial: str, pesos: List[int]) -> str:
        soma = sum(int(d) * p for d, p in zip(cnpj_parcial, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    return cnpj[-2:] == calcular_digito(cnpj[:12], pesos1) + calcular_digito(
        cnpj[:13], pesos2
    )


def validar_email(email: str) -> bool:
    """Valida formato de email"""
    padrao = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(padrao, email) is not None


def validar_telefone(telefone: str) -> bool:
    """Valida telefone brasileiro (com DDD)"""
    telefone = re.sub(r"[^0-9]", "", telefone)
    # Aceita 10 dígitos (DDD + 8) ou 11 dígitos (DDD + 9)
    return len(telefone) in [10, 11] and telefone[0] != "0"


def validar_chave_pix(chave: str, tipo: TipoChavePix) -> bool:
    """Valida chave PIX de acordo com o tipo"""
    if tipo == TipoChavePix.CPF:
        return validar_cpf(chave)
    elif tipo == TipoChavePix.CNPJ:
        return validar_cnpj(chave)
    elif tipo == TipoChavePix.EMAIL:
        return validar_email(chave)
    elif tipo == TipoChavePix.TELEFONE:
        return validar_telefone(chave)
    elif tipo == TipoChavePix.ALEATORIA:
        # Chave aleatória: UUID ou formato similar
        return len(chave) >= 32
    return False


# ============================================================================
# EXCEÇÕES CUSTOMIZADAS
# ============================================================================


class FinancialServiceError(Exception):
    """Exceção base para erros do serviço financeiro"""

    pass


class APIBancariaError(FinancialServiceError):
    """Erro de comunicação com API bancária"""

    pass


class PagamentoError(FinancialServiceError):
    """Erro no processamento de pagamento"""

    pass


class ConciliacaoError(FinancialServiceError):
    """Erro na conciliação bancária"""

    pass


# ============================================================================
# GERADORES DE PAGAMENTO
# ============================================================================


class GeradorPIX:
    """Gerador de pagamentos PIX"""

    def __init__(
        self,
        chave_pix: str,
        tipo_chave: TipoChavePix,
        banco: BancoSuportado,
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
    ):
        """
        Inicializa gerador PIX

        Args:
            chave_pix: Chave PIX (CPF, e-mail, telefone, etc.)
            tipo_chave: Tipo da chave PIX
            banco: Banco emissor
            gerenciador_evidencias: Gerenciador de evidências
        """
        self.chave_pix = chave_pix
        self.tipo_chave = tipo_chave
        self.banco = banco
        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()

        # API Keys de variáveis de ambiente (NUNCA hardcode!)
        self.api_key = os.getenv(f"API_KEY_{banco.name}", "")
        self.api_secret = os.getenv(f"API_SECRET_{banco.name}", "")

        if not self.api_key or not self.api_secret:
            logger.warning(
                f"Credenciais não configuradas para {banco.name}. "
                "Configure as variáveis de ambiente API_KEY_{banco} e API_SECRET_{banco}"
            )

        logger.info(f"Gerador PIX inicializado - Banco: {banco.name}")

    def gerar_pix(
        self,
        valor: Decimal,
        descricao: str,
        identificador: Optional[str] = None,
        vencimento: Optional[datetime] = None,
    ) -> Dict:
        """
        Gera cobrança PIX

        Args:
            valor: Valor da cobrança
            descricao: Descrição/finalidade do pagamento
            identificador: Identificador único (txid)
            vencimento: Data de vencimento (opcional)

        Returns:
            Dict com dados do PIX gerado

        Raises:
            ValueError: Se parâmetros são inválidos
        """
        logger.info(f"Gerando PIX: R$ {valor:.2f} - {descricao}")

        # Validações
        if valor < PIX_VALOR_MINIMO:
            raise ValueError(f"Valor mínimo para PIX é R$ {PIX_VALOR_MINIMO}")

        if valor > PIX_VALOR_MAXIMO:
            raise ValueError(f"Valor máximo para PIX é R$ {PIX_VALOR_MAXIMO}")

        if not descricao or not descricao.strip():
            raise ValueError("Descrição é obrigatória")

        if len(descricao) > PIX_DESCRICAO_MAX_CHARS:
            logger.warning(
                f"Descrição truncada de {len(descricao)} para {PIX_DESCRICAO_MAX_CHARS} caracteres"
            )
            descricao = descricao[:PIX_DESCRICAO_MAX_CHARS]

        # Valida chave PIX
        if not validar_chave_pix(self.chave_pix, self.tipo_chave):
            logger.warning(f"Chave PIX pode estar inválida: {self.chave_pix}")

        # Valida vencimento (não pode ser retroativo)
        if vencimento and vencimento < datetime.now():
            raise ValueError(
                f"Data de vencimento não pode ser retroativa: {vencimento}"
            )

        # Gera identificador único (txid)
        if identificador is None:
            identificador = str(uuid.uuid4())[:35]  # Máximo 35 caracteres

        # Monta payload PIX (padrão EMV)
        payload_pix = self._montar_payload_emv(
            chave=self.chave_pix,
            valor=valor,
            identificador=identificador,
            descricao=descricao,
        )

        # Gera QR Code (simulação - em produção usar biblioteca qrcode)
        qr_code_base64 = self._gerar_qrcode(payload_pix)

        # Gera Copia e Cola
        copia_cola = payload_pix

        # Resultado
        resultado = {
            "txid": identificador,
            "chave_pix": self.chave_pix,
            "tipo_chave": self.tipo_chave.value,
            "valor": float(valor),
            "descricao": descricao,
            "payload_emv": payload_pix,
            "qr_code_base64": qr_code_base64,
            "copia_cola": copia_cola,
            "vencimento": vencimento.isoformat() if vencimento else None,
            "criado_em": datetime.now().isoformat(),
            "status": StatusPagamento.PENDENTE.value,
            "banco": self.banco.value,
        }

        # Registra evidência
        hash_payload = hashlib.sha256(payload_pix.encode("utf-8")).hexdigest()
        try:
            self.gerenciador.registrar_evidencia(
                tipo="geracao_pix",
                descricao="PIX gerado - TxID: %s" % identificador,
                dados={
                    "txid": identificador,
                    "valor": float(valor),
                    "hash_payload": hash_payload,
                    "chave_pix": self.chave_pix,
                    "banco": self.banco.name,
                },
            )
        except Exception:
            logger.exception(
                "Falha ao registrar evidência de geração de PIX; ignorando"
            )

        logger.info(f"PIX gerado com sucesso - TxID: {identificador}")
        return resultado

    def consultar_pix(self, txid: str) -> Dict:
        """
        Consulta status de cobrança PIX

        NOTA: Em produção, fazer requisição à API do banco

        Args:
            txid: Identificador da transação

        Returns:
            Dict com status do PIX
        """
        logger.info(f"Consultando PIX: {txid}")

        # SIMULAÇÃO: Em produção, fazer requisição HTTP à API
        # headers = {
        #     'Authorization': f'Bearer {self._obter_token_acesso()}',
        #     'Content-Type': 'application/json'
        # }
        # response = requests.get(f'{url_api}/pix/{txid}', headers=headers)

        # Simula resposta
        resultado = {
            "txid": txid,
            "status": StatusPagamento.PENDENTE.value,
            "consultado_em": datetime.now().isoformat(),
        }

        return resultado

    def _montar_payload_emv(
        self, chave: str, valor: Decimal, identificador: str, descricao: str
    ) -> str:
        """
        Monta payload PIX no padrão EMV

        Args:
            chave: Chave PIX
            valor: Valor da cobrança
            identificador: TxID
            descricao: Descrição

        Returns:
            String com payload EMV
        """
        # Formato simplificado do payload EMV
        # Em produção, usar biblioteca específica ou seguir especificação completa

        payload = (
            "00020126"  # Payload Format Indicator
            f"0014BR.GOV.BCB.PIX01{len(chave):02d}{chave}"  # Merchant Account Information
            "52040000"  # Merchant Category Code
            "5303986"  # Currency (BRL = 986)
            f"54{len(str(valor)):02d}{valor:.2f}"  # Transaction Amount
            "5802BR"  # Country Code
            f"59{len(descricao):02d}{descricao}"  # Merchant Name
            "6014"  # City
            f"05{len(identificador):02d}{identificador}"  # TxID
        )

        # Adiciona CRC (simplificado)
        crc = self._calcular_crc16(payload + "6304")
        payload += f"6304{crc}"

        return payload

    def _calcular_crc16(self, payload: str) -> str:
        """Calcula CRC16 do payload PIX (simplificado)"""
        # Implementação simplificada
        # Em produção, usar algoritmo CRC16-CCITT correto
        crc = 0xFFFF
        for char in payload:
            crc ^= ord(char) << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return f"{crc:04X}"

    def _gerar_qrcode(self, payload: str) -> str:
        """
        Gera QR Code do PIX (Base64)

        NOTA: Em produção, usar biblioteca qrcode

        Args:
            payload: Payload EMV

        Returns:
            QR Code em Base64
        """
        # SIMULAÇÃO: Em produção usar:
        # import qrcode
        # qr = qrcode.QRCode(version=1, box_size=10, border=5)
        # qr.add_data(payload)
        # qr.make(fit=True)
        # img = qr.make_image(fill_color="black", back_color="white")
        # buffered = BytesIO()
        # img.save(buffered, format="PNG")
        # img_str = base64.b64encode(buffered.getvalue()).decode()

        # Placeholder QR generation: do not depend on external libraries.
        # Log intent and return a deterministic base64 placeholder so callers
        # receive a valid data URL without requiring qrcode/Pillow.
        try:
            logger.debug("Gerando QR Code (placeholder)")
            simulated_qr = base64.b64encode(payload.encode("utf-8")).decode()
            return "data:image/png;base64,%s" % simulated_qr
        except Exception:
            logger.exception("Falha ao gerar QR Code placeholder")
            return "data:image/png;base64," + ""


class GeradorBoleto:
    """Gerador de boletos bancários"""

    def __init__(
        self,
        banco: BancoSuportado,
        cedente_dados: Dict,
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
    ):
        """
        Inicializa gerador de boletos

        Args:
            banco: Banco emissor
            cedente_dados: Dados do cedente (empresa)
            gerenciador_evidencias: Gerenciador de evidências
        """
        self.banco = banco
        self.cedente = cedente_dados
        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()

        # API Keys de variáveis de ambiente
        self.api_key = os.getenv(f"API_KEY_{banco.name}", "")
        self.api_secret = os.getenv(f"API_SECRET_{banco.name}", "")

        if not self.api_key or not self.api_secret:
            logger.warning(
                f"Credenciais não configuradas para {banco.name}. "
                "Configure as variáveis de ambiente API_KEY_{banco} e API_SECRET_{banco}"
            )

        logger.info(f"Gerador de Boletos inicializado - Banco: {banco.name}")

    def gerar_boleto(
        self,
        sacado_dados: Dict,
        valor: Decimal,
        vencimento: datetime,
        numero_documento: Optional[str] = None,
        instrucoes: Optional[List[str]] = None,
    ) -> Dict:
        """
        Gera boleto bancário

        Args:
            sacado_dados: Dados do sacado (pagador)
            valor: Valor do boleto
            vencimento: Data de vencimento
            numero_documento: Número do documento
            instrucoes: Instruções para o caixa

        Returns:
            Dict com dados do boleto gerado

        Raises:
            ValueError: Se parâmetros são inválidos
        """
        logger.info(f"Gerando boleto: R$ {valor:.2f} - Vencimento: {vencimento}")

        # Validações
        if valor < BOLETO_VALOR_MINIMO:
            raise ValueError(f"Valor mínimo para boleto é R$ {BOLETO_VALOR_MINIMO}")

        if valor > BOLETO_VALOR_MAXIMO:
            raise ValueError(f"Valor máximo para boleto é R$ {BOLETO_VALOR_MAXIMO}")

        if not sacado_dados:
            raise ValueError("Dados do sacado são obrigatórios")

        # Valida campos obrigatórios do sacado
        campos_obrigatorios = ["nome", "documento"]
        campos_faltantes = [c for c in campos_obrigatorios if c not in sacado_dados]
        if campos_faltantes:
            raise ValueError(
                f"Campos obrigatórios do sacado faltando: {', '.join(campos_faltantes)}"
            )

        # Valida documento do sacado (CPF ou CNPJ)
        documento = sacado_dados.get("documento", "")
        documento_numeros = re.sub(r"[^0-9]", "", documento)
        if len(documento_numeros) == 11:
            if not validar_cpf(documento):
                logger.warning(f"CPF do sacado pode estar inválido: {documento}")
        elif len(documento_numeros) == 14:
            if not validar_cnpj(documento):
                logger.warning(f"CNPJ do sacado pode estar inválido: {documento}")
        else:
            logger.warning(
                f"Documento do sacado em formato não reconhecido: {documento}"
            )

        # Valida vencimento
        if vencimento < datetime.now():
            raise ValueError(
                f"Data de vencimento não pode ser retroativa: {vencimento}"
            )

        # Aviso se vencimento muito distante (> 1 ano)
        if vencimento > datetime.now() + timedelta(days=365):
            logger.warning(f"Vencimento muito distante: {vencimento}")

        # Gera número do documento se não fornecido
        if numero_documento is None:
            numero_documento = datetime.now().strftime("%Y%m%d%H%M%S")

        # Gera nosso número (identificador único do boleto no banco)
        nosso_numero = self._gerar_nosso_numero()

        # Gera linha digitável e código de barras
        linha_digitavel, codigo_barras = self._gerar_codigo_barras(
            valor=valor,
            vencimento=vencimento,
            nosso_numero=nosso_numero,
        )

        # Resultado
        resultado = {
            "numero_documento": numero_documento,
            "nosso_numero": nosso_numero,
            "linha_digitavel": linha_digitavel,
            "codigo_barras": codigo_barras,
            "valor": float(valor),
            "vencimento": vencimento.isoformat(),
            "cedente": self.cedente,
            "sacado": sacado_dados,
            "instrucoes": instrucoes or [],
            "banco": self.banco.value,
            "criado_em": datetime.now().isoformat(),
            "status": StatusPagamento.PENDENTE.value,
        }

        # Registra evidência
        hash_codigo_barras = hashlib.sha256(codigo_barras.encode("utf-8")).hexdigest()
        try:
            self.gerenciador.registrar_evidencia(
                tipo="geracao_boleto",
                descricao="Boleto gerado - Nosso Número: %s" % nosso_numero,
                dados={
                    "nosso_numero": nosso_numero,
                    "valor": float(valor),
                    "vencimento": vencimento.isoformat(),
                    "hash_codigo_barras": hash_codigo_barras,
                    "banco": self.banco.name,
                },
            )
        except Exception:
            logger.exception(
                "Falha ao registrar evidência de geração de boleto; ignorando"
            )

        logger.info(f"Boleto gerado com sucesso - Nosso Número: {nosso_numero}")
        return resultado

    def consultar_boleto(self, nosso_numero: str) -> Dict:
        """
        Consulta status de boleto

        Args:
            nosso_numero: Identificador do boleto

        Returns:
            Dict com status do boleto
        """
        logger.info(f"Consultando boleto: {nosso_numero}")

        # SIMULAÇÃO: Em produção, fazer requisição à API do banco
        resultado = {
            "nosso_numero": nosso_numero,
            "status": StatusPagamento.PENDENTE.value,
            "consultado_em": datetime.now().isoformat(),
        }

        return resultado

    def _gerar_nosso_numero(self) -> str:
        """Gera nosso número do boleto"""
        # Formato simplificado: timestamp + 4 dígitos aleatórios
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_digits = str(uuid.uuid4().int)[:4]
        nosso_numero = f"{timestamp}{random_digits}"
        return nosso_numero[:17]  # Máximo 17 dígitos

    def _gerar_codigo_barras(
        self, valor: Decimal, vencimento: datetime, nosso_numero: str
    ) -> Tuple[str, str]:
        """
        Gera código de barras e linha digitável do boleto

        Args:
            valor: Valor do boleto
            vencimento: Data de vencimento
            nosso_numero: Nosso número

        Returns:
            Tupla (linha_digitavel, codigo_barras)
        """
        # Formato simplificado (em produção, seguir padrão FEBRABAN)

        # Código do banco (3 dígitos)
        codigo_banco = self.banco.value

        # Código da moeda (sempre 9 para Real)
        codigo_moeda = "9"

        # Fator de vencimento (dias desde 07/10/1997)
        data_base = datetime(1997, 10, 7)
        fator_vencimento = (vencimento - data_base).days

        # Valor (10 dígitos, sem separador decimal)
        valor_str = f"{int(valor * 100):010d}"

        # Campo livre (25 dígitos) - simplificado
        campo_livre = f"{nosso_numero:0<25}"[:25]

        # DV geral (simplificado)
        dv_geral = "1"

        # Código de barras
        codigo_barras = (
            f"{codigo_banco}{codigo_moeda}{dv_geral}{fator_vencimento:04d}"
            f"{valor_str}{campo_livre}"
        )

        # Linha digitável (código de barras formatado em blocos)
        linha_digitavel = self._formatar_linha_digitavel(codigo_barras)

        return linha_digitavel, codigo_barras

    def _formatar_linha_digitavel(self, codigo_barras: str) -> str:
        """Formata código de barras em linha digitável"""
        # Formato simplificado: 5 blocos separados
        # Em produção, seguir regras completas da FEBRABAN

        blocos = [
            codigo_barras[0:5],
            codigo_barras[5:10],
            codigo_barras[10:15],
            codigo_barras[15:20],
            codigo_barras[20:25],
            codigo_barras[25:30],
            codigo_barras[30:35],
            codigo_barras[35:40],
            codigo_barras[40:44],
        ]

        linha = ".".join(blocos)
        return linha


# ============================================================================
# SERVIÇO DE CONCILIAÇÃO BANCÁRIA
# ============================================================================


class ServicoConciliacao:
    """Serviço de conciliação bancária automática"""

    def __init__(self, gerenciador_evidencias: Optional[GerenciadorEvidencias] = None):
        """
        Inicializa serviço de conciliação

        Args:
            gerenciador_evidencias: Gerenciador de evidências
        """
        self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()
        # Lock to protect any shared internal counters/state
        self._lock = threading.Lock()
        logger.info("Serviço de Conciliação inicializado")

    def conciliar_pagamento(
        self,
        pagamento_esperado: Dict,
        extrato_bancario: List[Dict],
        tolerancia_valor: Decimal = Decimal("0.01"),
        tolerancia_dias: int = 3,
    ) -> Dict:
        """
        Concilia pagamento com extrato bancário

        Args:
            pagamento_esperado: Dados do pagamento esperado
            extrato_bancario: Lista de lançamentos do extrato
            tolerancia_valor: Tolerância para diferença de valor
            tolerancia_dias: Tolerância em dias para data

        Returns:
            Dict com resultado da conciliação

        Raises:
            ValueError: Se parâmetros são inválidos
        """
        logger.info(f"Conciliando pagamento: {pagamento_esperado.get('id', 'N/A')}")

        # Validações (ordem: primeiro valida parâmetros, depois verifica extrato vazio)
        if not pagamento_esperado:
            raise ValueError("Pagamento esperado não pode estar vazio")

        # Valida campos obrigatórios
        if "valor" not in pagamento_esperado:
            raise ValueError("Campo 'valor' é obrigatório em pagamento_esperado")

        if "data" not in pagamento_esperado:
            raise ValueError("Campo 'data' é obrigatório em pagamento_esperado")

        # Valida tolerâncias
        if tolerancia_valor < 0:
            raise ValueError("Tolerância de valor não pode ser negativa")

        if tolerancia_dias < 0:
            raise ValueError("Tolerância de dias não pode ser negativa")

        # Verifica extrato vazio (após validar parâmetros)
        if not extrato_bancario:
            logger.warning("Extrato bancário vazio - sem dados para conciliar")
            return {
                "conciliado": False,
                "score": 0.0,
                "lancamento_encontrado": None,
                "total_correspondencias": 0,
                "motivo": "Extrato vazio",
            }

        # Dados do pagamento esperado
        try:
            valor_esperado = Decimal(str(pagamento_esperado.get("valor", 0)))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Valor inválido em pagamento_esperado: {e}")

        try:
            data_esperada = datetime.fromisoformat(pagamento_esperado.get("data", ""))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Data inválida em pagamento_esperado: {e}")

        identificador = pagamento_esperado.get("identificador", "")

        # Busca correspondências no extrato
        correspondencias = []

        for i, lancamento in enumerate(extrato_bancario):
            # Valida lançamento
            if not isinstance(lancamento, dict):
                logger.warning(f"Lançamento {i} não é um dicionário - ignorando")
                continue

            if "valor" not in lancamento or "data" not in lancamento:
                logger.warning(f"Lançamento {i} sem campos obrigatórios - ignorando")
                continue

            try:
                valor_lancamento = Decimal(str(lancamento.get("valor", 0)))
                data_lancamento = datetime.fromisoformat(lancamento.get("data", ""))
            except (ValueError, TypeError) as e:
                logger.warning(f"Erro ao processar lançamento {i}: {e} - ignorando")
                continue

            # Verifica tolerância de valor
            diferenca_valor = abs(valor_lancamento - valor_esperado)
            if diferenca_valor > tolerancia_valor:
                continue

            # Verifica tolerância de data
            diferenca_dias = abs((data_lancamento - data_esperada).days)
            if diferenca_dias > tolerancia_dias:
                continue

            # Verifica identificador (se disponível)
            historico = lancamento.get("historico", "").lower()
            if identificador and identificador.lower() not in historico:
                # Score menor se identificador não confere
                score = 0.7
            else:
                score = 1.0

            # Ajusta score baseado em diferenças
            if diferenca_valor > 0 and valor_esperado > 0:
                penalidade_valor = min(
                    0.2, float(diferenca_valor / valor_esperado) * 0.3
                )
                score -= penalidade_valor

            if diferenca_dias > 0 and tolerancia_dias > 0:
                penalidade_dias = min(0.2, (diferenca_dias / tolerancia_dias) * 0.2)
                score -= penalidade_dias

            correspondencias.append(
                {
                    "lancamento": lancamento,
                    "score": max(0.0, min(1.0, score)),  # Garante 0.0-1.0
                    "diferenca_valor": float(diferenca_valor),
                    "diferenca_dias": diferenca_dias,
                }
            )

        # Ordena por score
        correspondencias.sort(key=lambda x: x["score"], reverse=True)

        # Define resultado
        if correspondencias:
            melhor_correspondencia = correspondencias[0]
            conciliado = melhor_correspondencia["score"] >= 0.8

            resultado = {
                "conciliado": conciliado,
                "score": melhor_correspondencia["score"],
                "lancamento_encontrado": melhor_correspondencia["lancamento"],
                "diferenca_valor": melhor_correspondencia["diferenca_valor"],
                "diferenca_dias": melhor_correspondencia["diferenca_dias"],
                "outras_correspondencias": correspondencias[1:5],  # Até 5 alternativas
                "total_correspondencias": len(correspondencias),
            }
        else:
            resultado = {
                "conciliado": False,
                "score": 0.0,
                "lancamento_encontrado": None,
                "total_correspondencias": 0,
            }

        # Registra evidência (protegido por lock)
        try:
            with getattr(self, "_lock", threading.Lock()):
                self.gerenciador.registrar_evidencia(
                    tipo="conciliacao_bancaria",
                    descricao=(
                        "Conciliação processada - %s"
                        % ("Sucesso" if resultado["conciliado"] else "Falha")
                    ),
                    dados={
                        "pagamento_id": pagamento_esperado.get("id"),
                        "conciliado": resultado["conciliado"],
                        "score": resultado["score"],
                        "valor_esperado": float(valor_esperado),
                    },
                )
        except Exception:
            logger.exception("Erro ao registrar evidência de conciliação; ignorando")

        logger.info(
            f"Conciliação concluída - Conciliado: {resultado['conciliado']} "
            f"(Score: {resultado['score']:.2f})"
        )

        return resultado

    def processar_lote_conciliacao(
        self,
        pagamentos: List[Dict],
        extrato_bancario: List[Dict],
    ) -> Dict:
        """
        Processa lote de conciliações

        Args:
            pagamentos: Lista de pagamentos esperados
            extrato_bancario: Extrato bancário completo

        Returns:
            Dict com estatísticas do lote
        """
        logger.info(f"Processando lote de conciliação: {len(pagamentos)} pagamentos")

        resultados = []
        conciliados = 0
        nao_conciliados = 0

        for pagamento in pagamentos:
            resultado = self.conciliar_pagamento(pagamento, extrato_bancario)
            resultados.append(
                {
                    "pagamento": pagamento,
                    "resultado": resultado,
                }
            )

            if resultado["conciliado"]:
                conciliados += 1
            else:
                nao_conciliados += 1

        estatisticas = {
            "total": len(pagamentos),
            "conciliados": conciliados,
            "nao_conciliados": nao_conciliados,
            "taxa_conciliacao": (
                (conciliados / len(pagamentos) * 100) if pagamentos else 0
            ),
            "resultados": resultados,
            "processado_em": datetime.now().isoformat(),
        }

        logger.info(
            f"Lote concluído - {conciliados}/{len(pagamentos)} conciliados "
            f"({estatisticas['taxa_conciliacao']:.1f}%)"
        )

        return estatisticas


# ============================================================================
# SERVIÇO FINANCEIRO PRINCIPAL
# ============================================================================


class FinancialService:
    """Serviço principal de integrações bancárias e financeiras"""

    # Thread-safe singleton support
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(FinancialService, cls).__new__(cls)
        return cls._instance

    def __init__(
        self,
        banco_padrao: BancoSuportado = BancoSuportado.BANCO_DO_BRASIL,
        gerenciador_evidencias: Optional[GerenciadorEvidencias] = None,
    ):
        """
        Inicializa serviço financeiro

        Args:
            banco_padrao: Banco padrão para operações
            gerenciador_evidencias: Gerenciador de evidências
        """
        # init guard: avoid reinitializing singleton state
        if getattr(self, "_initialized", False):
            return

        self._init_lock = threading.Lock()
        with self._init_lock:
            self.banco_padrao = banco_padrao
            self.gerenciador = gerenciador_evidencias or GerenciadorEvidencias()

            # Serviços especializados
            self.conciliacao = ServicoConciliacao(self.gerenciador)

            # simple in-memory cache + lock for shared resources
            self._cache = {}
            self._cache_lock = threading.Lock()

            logger.info(
                "FinancialService inicializado - Banco padrão: %s" % banco_padrao.name
            )
            self._initialized = True

    def gerar_pix(
        self,
        chave_pix: str,
        tipo_chave: TipoChavePix,
        valor: Decimal,
        descricao: str,
        banco: Optional[BancoSuportado] = None,
        vencimento: Optional[datetime] = None,
    ) -> Dict:
        """
        Gera cobrança PIX

        Args:
            chave_pix: Chave PIX
            tipo_chave: Tipo da chave
            valor: Valor da cobrança
            descricao: Descrição do pagamento
            banco: Banco emissor (usa padrão se não fornecido)
            vencimento: Data de vencimento (opcional)

        Returns:
            Dict com dados do PIX gerado
        """
        banco = banco or self.banco_padrao

        gerador = GeradorPIX(chave_pix, tipo_chave, banco, self.gerenciador)
        return gerador.gerar_pix(valor, descricao, vencimento=vencimento)

    def gerar_boleto(
        self,
        cedente_dados: Dict,
        sacado_dados: Dict,
        valor: Decimal,
        vencimento: datetime,
        banco: Optional[BancoSuportado] = None,
        numero_documento: Optional[str] = None,
        instrucoes: Optional[List[str]] = None,
    ) -> Dict:
        """
        Gera boleto bancário

        Args:
            cedente_dados: Dados do cedente (empresa)
            sacado_dados: Dados do sacado (pagador)
            valor: Valor do boleto
            vencimento: Data de vencimento
            banco: Banco emissor (usa padrão se não fornecido)
            numero_documento: Número do documento
            instrucoes: Instruções para o caixa

        Returns:
            Dict com dados do boleto gerado
        """
        banco = banco or self.banco_padrao

        gerador = GeradorBoleto(banco, cedente_dados, self.gerenciador)
        return gerador.gerar_boleto(
            sacado_dados, valor, vencimento, numero_documento, instrucoes
        )

    def conciliar_pagamento(
        self,
        pagamento_esperado: Dict,
        extrato_bancario: List[Dict],
        tolerancia_valor: Decimal = Decimal("0.01"),
        tolerancia_dias: int = 3,
    ) -> Dict:
        """
        Concilia pagamento com extrato bancário

        Args:
            pagamento_esperado: Dados do pagamento esperado
            extrato_bancario: Lista de lançamentos do extrato
            tolerancia_valor: Tolerância para diferença de valor
            tolerancia_dias: Tolerância em dias para data

        Returns:
            Dict com resultado da conciliação
        """
        return self.conciliacao.conciliar_pagamento(
            pagamento_esperado, extrato_bancario, tolerancia_valor, tolerancia_dias
        )

    def processar_pagamento(
        self,
        tipo: TipoPagamento,
        dados_pagamento: Dict,
    ) -> Dict:
        """
        Processa pagamento (PIX, TED, DOC, etc.)

        NOTA: Em produção, integrar com API do banco
        """
        logger.info("Processando pagamento: %s" % tipo.value)

        # Provide an async implementation and a sync bridge so callers can use
        # either model. Protect external calls with granular try/except and
        # never allow exceptions from network/libs to bubble out.

        async def _process_async():
            try:
                # Simulate network latency / API call
                try:
                    import asyncio as _asyncio

                    await _asyncio.sleep(0.01)
                except Exception:
                    # In case asyncio.sleep misbehaves (very unlikely), ignore
                    pass

                protocolo = str(uuid.uuid4())
                resultado_local = {
                    "tipo": tipo.value,
                    "protocolo": protocolo,
                    "status": StatusPagamento.PROCESSANDO.value,
                    "dados": dados_pagamento,
                    "processado_em": datetime.now().isoformat(),
                }

                # safe evidence registration
                try:
                    self.gerenciador.registrar_evidencia(
                        tipo="processamento_pagamento",
                        descricao=("Pagamento processado - Tipo: %s" % tipo.value),
                        dados={
                            "protocolo": protocolo,
                            "tipo": tipo.value,
                            "valor": dados_pagamento.get("valor"),
                        },
                    )
                except Exception:
                    logger.exception(
                        "Falha ao registrar evidência de processamento de pagamento"
                    )

                return resultado_local
            except Exception as e:
                logger.exception("Erro ao processar pagamento async: %s" % e)
                raise APIBancariaError("Erro ao processar pagamento")

        # Bridge: if an event loop is already running, execute async in a
        # dedicated thread with its own event loop. Otherwise use asyncio.run
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():

            def _run_in_thread():
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(_process_async())
                finally:
                    try:
                        new_loop.close()
                    except Exception:
                        pass

            from concurrent.futures import ThreadPoolExecutor as _TPE

            with _TPE(max_workers=1) as ex:
                fut = ex.submit(_run_in_thread)
                return fut.result()

        # No running loop: safe to run normally
        try:
            return asyncio.run(_process_async())
        except Exception:
            logger.exception("Erro ao processar pagamento (sync)")
            raise APIBancariaError("Erro ao processar pagamento")


# Funções auxiliares de uso rápido (nível de módulo)


def gerar_pix_rapido(
    chave_pix: str,
    valor: Decimal,
    descricao: str,
    tipo_chave: TipoChavePix = TipoChavePix.CPF,
) -> Dict:
    """
    Função rápida para gerar PIX

    Args:
        chave_pix: Chave PIX
        valor: Valor da cobrança
        descricao: Descrição
        tipo_chave: Tipo da chave (padrão: CPF)

    Returns:
        Dict com dados do PIX
    """
    service = FinancialService()
    return service.gerar_pix(chave_pix, tipo_chave, valor, descricao)


def conciliar_pagamento_rapido(pagamento: Dict, extrato: List[Dict]) -> Dict:
    """
    Função rápida para conciliar pagamento

    Args:
        pagamento: Pagamento esperado
        extrato: Extrato bancário

    Returns:
        Dict com resultado da conciliação
    """
    service = FinancialService()
    return service.conciliar_pagamento(pagamento, extrato)


# Exportações públicas
__all__ = [
    "FinancialService",
    "GeradorPIX",
    "GeradorBoleto",
    "ServicoConciliacao",
    "TipoPagamento",
    "StatusPagamento",
    "TipoChavePix",
    "BancoSuportado",
    "FinancialServiceError",
    "APIBancariaError",
    "PagamentoError",
    "ConciliacaoError",
    "gerar_pix_rapido",
    "conciliar_pagamento_rapido",
    "GerenciadorEvidencias",
]
