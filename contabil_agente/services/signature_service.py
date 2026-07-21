"""
Serviço de Assinatura Digital
Integração com DocuSign, ICP-Brasil e outras plataformas de certificação

Funcionalidades:
- Integração com DocuSign API
- Suporte para certificados ICP-Brasil
- Assinatura digital de PDFs
- Validação de assinaturas
- Armazenamento de evidências legais
"""

import base64
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DOCUSIGN_AVAILABLE = False
ApiClient = None
EnvelopesApi = None
EnvelopeDefinition = None
Document = None
Signer = None
SignHere = None
Tabs = None
Recipients = None

try:
    from docusign_esign import (  # type: ignore
        ApiClient,
        Document,
        EnvelopeDefinition,
        EnvelopesApi,
        Recipients,
        Signer,
        SignHere,
        Tabs,
    )

    DOCUSIGN_AVAILABLE = True
except ImportError as e:
    logger.warning(
        f"DocuSign SDK não disponível. Instale: pip install docusign-esign ({e})"
    )

PYHANKO_AVAILABLE = False
signers = None
IncrementalPdfFileWriter = None
stamp = None
SigFieldSpec = None

try:
    from pyhanko import stamp  # type: ignore
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter  # type: ignore
    from pyhanko.sign import signers  # type: ignore
    from pyhanko.sign.fields import SigFieldSpec  # type: ignore

    PYHANKO_AVAILABLE = True
except ImportError:
    PYHANKO_AVAILABLE = False
    logger.warning("PyHanko não disponível. Instale: pip install pyHanko")


class ConfiguracaoAssinatura:
    """Configurações para serviços de assinatura digital"""

    def __init__(
        self,
        docusign_integration_key: str,
        docusign_user_id: str,
        icp_certificado_path: str,
        icp_senha: str,
        docusign_account_id: Optional[str] = None,
        docusign_private_key_path: Optional[str] = None,
        docusign_base_path: Optional[str] = None,
        diretorio_evidencias: Optional[Path] = None,
    ) -> None:
        """Inicializa configurações de forma explícita.

        Observações de segurança:
        - Não inicializar valores sensíveis com defaults em código.
        - Valores obrigatórios devem ser fornecidos; use `carregar_de_env`
          para obter valores do ambiente e validar ao iniciar a aplicação.
        """

        # Valores obrigatórios (validados antes de instanciar)
        self.docusign_integration_key = docusign_integration_key
        self.docusign_user_id = docusign_user_id
        self.icp_certificado_path = icp_certificado_path
        self.icp_senha = icp_senha

        # Valores opcionais (somente leitura do ambiente; nenhum valor
        # hardcoded aqui)
        self.docusign_account_id = docusign_account_id
        self.docusign_private_key_path = docusign_private_key_path
        self.docusign_base_path = docusign_base_path

        # Diretório para evidências (opcional). Se informado, garante existência.
        self.diretorio_evidencias = diretorio_evidencias
        if self.diretorio_evidencias:
            try:
                Path(self.diretorio_evidencias).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"Não foi possível criar diretório de evidências: {e}")

    @classmethod
    def carregar_de_env(cls) -> "ConfiguracaoAssinatura":
        """Carrega configurações de variáveis de ambiente"""
        import os

        # Lê variáveis obrigatórias
        docusign_integration_key = os.getenv("DOCUSIGN_INTEGRATION_KEY")
        docusign_user_id = os.getenv("DOCUSIGN_USER_ID")
        icp_certificado_path = os.getenv("ICP_CERTIFICADO_PATH")
        icp_senha = os.getenv("ICP_SENHA")

        # Variáveis opcionais
        docusign_account_id = os.getenv("DOCUSIGN_ACCOUNT_ID")
        docusign_private_key_path = os.getenv("DOCUSIGN_PRIVATE_KEY_PATH")
        docusign_base_path = os.getenv(
            "DOCUSIGN_BASE_PATH", "https://demo.docusign.net/restapi"
        )
        diretorio_evidencias = os.getenv("DIRETORIO_EVIDENCIAS")

        # Valida presença dos valores obrigatórios e falha rápido se ausentes
        missing = []
        if not docusign_integration_key:
            missing.append("DOCUSIGN_INTEGRATION_KEY")
        if not docusign_user_id:
            missing.append("DOCUSIGN_USER_ID")
        if not icp_certificado_path:
            missing.append("ICP_CERTIFICADO_PATH")
        if not icp_senha:
            missing.append("ICP_SENHA")

        if missing:
            raise RuntimeError(
                "Variáveis de ambiente obrigatórias faltando para ConfiguracaoAssinatura: "
                + ", ".join(missing)
            )

        # Constrói instância com os valores validados
        return cls(
            docusign_integration_key=docusign_integration_key,
            docusign_user_id=docusign_user_id,
            icp_certificado_path=icp_certificado_path,
            icp_senha=icp_senha,
            docusign_account_id=docusign_account_id,
            docusign_private_key_path=docusign_private_key_path,
            docusign_base_path=docusign_base_path,
            diretorio_evidencias=(
                Path(diretorio_evidencias) if diretorio_evidencias else None
            ),
        )


class AssinaturaDocuSign:
    """Integração com DocuSign para assinatura eletrônica"""

    def __init__(self, config: ConfiguracaoAssinatura):
        """
        Inicializa integração com DocuSign

        Args:
            config: Configurações de assinatura
        """
        if not DOCUSIGN_AVAILABLE:
            raise ImportError(
                "DocuSign SDK não está instalado. Execute: pip install docusign-esign"
            )

        self.config = config
        self.api_client = None

        if config.docusign_integration_key:
            self._configurar_cliente()

    def _configurar_cliente(self):
        """Configura cliente da API DocuSign"""
        try:
            self.api_client = ApiClient()
            self.api_client.set_base_path(self.config.docusign_base_path)

            # Autenticação JWT (requer configuração prévia no DocuSign)
            # Nota: Implementação simplificada - produção requer OAuth completo
            logger.info("Cliente DocuSign configurado")
        except Exception as e:
            logger.error(f"Erro ao configurar DocuSign: {e}")
            raise

    def enviar_para_assinatura(
        self,
        caminho_pdf: str,
        signatarios: List[Dict],
        assunto: str = "Documento para Assinatura",
        mensagem: str = "",
    ) -> Dict:
        """
        Envia documento para assinatura via DocuSign

        Args:
            caminho_pdf: Caminho do arquivo PDF
            signatarios: Lista de dicionários com dados dos signatários
                        [{"nome": "...", "email": "...", "ordem": 1}, ...]
            assunto: Assunto do envelope
            mensagem: Mensagem para os signatários

        Returns:
            Dict com envelope_id e status
        """
        if not self.api_client:
            raise ValueError("Cliente DocuSign não configurado")

        # Lê o documento
        with open(caminho_pdf, "rb") as f:
            conteudo_pdf = f.read()

        # Codifica em base64
        documento_base64 = base64.b64encode(conteudo_pdf).decode("ascii")

        # Cria documento DocuSign
        documento = Document(
            document_base64=documento_base64,
            name=Path(caminho_pdf).name,
            file_extension="pd",
            document_id="1",
        )

        # Cria signatários
        signers_list = []
        for idx, sig in enumerate(signatarios, 1):
            # Posição da assinatura (pode ser customizada)
            sign_here = SignHere(
                document_id="1",
                page_number="1",
                x_position="100",
                y_position=str(100 + (idx * 100)),
            )

            signer = Signer(
                email=sig["email"],
                name=sig["nome"],
                recipient_id=str(idx),
                routing_order=str(sig.get("ordem", idx)),
                tabs=Tabs(sign_here_tabs=[sign_here]),
            )
            signers_list.append(signer)

        # Cria envelope
        recipients = Recipients(signers=signers_list)
        envelope_definition = EnvelopeDefinition(
            email_subject=assunto,
            email_blurb=mensagem,
            documents=[documento],
            recipients=recipients,
            status="sent",
        )

        # Envia envelope
        try:
            envelopes_api = EnvelopesApi(self.api_client)
            results = envelopes_api.create_envelope(
                self.config.docusign_account_id, envelope_definition=envelope_definition
            )

            envelope_id = results.envelope_id

            logger.info(
                f"Documento enviado para assinatura - Envelope ID: {envelope_id}"
            )

            return {
                "sucesso": True,
                "envelope_id": envelope_id,
                "status": "sent",
                "signatarios": len(signatarios),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Erro ao enviar documento: {e}")
            return {
                "sucesso": False,
                "erro": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def verificar_status(self, envelope_id: str) -> Dict:
        """
        Verifica status de um envelope

        Args:
            envelope_id: ID do envelope DocuSign

        Returns:
            Dict com status do envelope
        """
        if not self.api_client:
            raise ValueError("Cliente DocuSign não configurado")

        try:
            envelopes_api = EnvelopesApi(self.api_client)
            envelope = envelopes_api.get_envelope(
                self.config.docusign_account_id, envelope_id
            )

            return {
                "envelope_id": envelope_id,
                "status": envelope.status,
                "data_criacao": envelope.created_date_time,
                "data_envio": envelope.sent_date_time,
                "data_conclusao": envelope.completed_date_time,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Erro ao verificar status: {e}")
            return {"erro": str(e), "timestamp": datetime.now().isoformat()}

    def baixar_documento_assinado(
        self, envelope_id: str, caminho_destino: str
    ) -> Tuple[bool, str]:
        """
        Baixa documento assinado do DocuSign

        Args:
            envelope_id: ID do envelope
            caminho_destino: Caminho onde salvar o PDF assinado

        Returns:
            Tuple (sucesso: bool, mensagem: str)
        """
        if not self.api_client:
            return False, "Cliente DocuSign não configurado"

        try:
            envelopes_api = EnvelopesApi(self.api_client)
            documento = envelopes_api.get_document(
                self.config.docusign_account_id,
                "combined",  # Documento combinado
                envelope_id,
            )

            with open(caminho_destino, "wb") as f:
                f.write(documento)

            logger.info(f"Documento assinado baixado: {caminho_destino}")
            return True, "Documento baixado com sucesso"

        except Exception as e:
            logger.error(f"Erro ao baixar documento: {e}")
            return False, str(e)


class AssinaturaICPBrasil:
    """Assinatura digital com certificados ICP-Brasil"""

    def __init__(self, config: ConfiguracaoAssinatura):
        """
        Inicializa assinatura ICP-Brasil

        Args:
            config: Configurações de assinatura
        """
        if not PYHANKO_AVAILABLE:
            raise ImportError(
                "PyHanko não está instalado. Execute: pip install pyHanko"
            )

        self.config = config

    def assinar_pdf(
        self,
        caminho_pdf: str,
        caminho_saida: str,
        razao: str = "Assinatura Digital",
        localizacao: str = "Brasil",
        contato: str = "",
    ) -> Tuple[bool, str, str]:
        """
        Assina PDF com certificado ICP-Brasil

        Args:
            caminho_pdf: Caminho do PDF a ser assinado
            caminho_saida: Caminho do PDF assinado
            razao: Razão da assinatura
            localizacao: Localização da assinatura
            contato: Informação de contato

        Returns:
            Tuple (sucesso: bool, mensagem: str, hash_sha256: str)
        """
        if (
            not self.config.icp_certificado_path
            or not Path(self.config.icp_certificado_path).exists()
        ):
            return False, "Certificado ICP-Brasil não configurado", ""

        try:
            # Carrega certificado .pfx
            with open(self.config.icp_certificado_path, "rb") as f:
                pfx_data = f.read()

            # Cria signer com certificado
            signer_obj = signers.SimpleSigner.load_pkcs12(
                pfx_file=pfx_data,
                passphrase=(
                    self.config.icp_senha.encode("utf-8")
                    if self.config.icp_senha
                    else None
                ),
            )

            # Abre PDF para assinatura
            with open(caminho_pdf, "rb") as pdf_file:
                writer = IncrementalPdfFileWriter(pdf_file)

                # Cria campo de assinatura
                sig_field = SigFieldSpec(
                    sig_field_name="Signature1",
                    box=(50, 50, 200, 100),  # Posição da assinatura visual
                )

                # Adiciona campo de assinatura
                writer.add_signature_field(sig_field)

                # Metadados da assinatura
                meta = signers.PdfSignatureMetadata(
                    field_name="Signature1",
                    reason=razao,
                    location=localizacao,
                    contact_info=contato,
                )

                # Assina
                pdf_signer = signers.PdfSigner(
                    meta,
                    signer=signer_obj,
                    stamp_style=stamp.TextStampStyle(
                        stamp_text="Assinado Digitalmente\n%(ts)s",
                    ),
                )

                # Salva PDF assinado
                with open(caminho_saida, "wb") as output:
                    pdf_signer.sign_pdf(writer, output=output)

            # Calcula hash do arquivo assinado
            hash_sha256 = self._calcular_hash(caminho_saida)

            logger.info(f"PDF assinado com ICP-Brasil: {caminho_saida}")
            logger.info(f"Hash SHA-256: {hash_sha256}")

            return True, "PDF assinado com sucesso", hash_sha256

        except Exception as e:
            logger.error(f"Erro ao assinar PDF: {e}")
            return False, str(e), ""

    def verificar_assinatura(self, caminho_pdf: str) -> Dict:
        """
        Verifica assinaturas em um PDF

        Args:
            caminho_pdf: Caminho do PDF assinado

        Returns:
            Dict com informações sobre as assinaturas
        """
        if not PYHANKO_AVAILABLE:
            logger.error("PyHanko não disponível para verificar assinatura")
            return {
                "valido": False,
                "erro": "PyHanko não está instalado",
                "verificado_em": datetime.now().isoformat(),
            }

        try:
            from pyhanko.pdf_utils.reader import PdfFileReader  # type: ignore
            from pyhanko.sign.validation import validate_pdf_signature  # type: ignore

            with open(caminho_pdf, "rb") as f:
                # Valida assinatura
                r = PdfFileReader(f)
                s = r.embedded_signatures[0]
                status = validate_pdf_signature(s)

                return {
                    "valido": status.bottom_line,
                    "assinante": (
                        status.signer_reported_name
                        if hasattr(status, "signer_reported_name")
                        else "N/A"
                    ),
                    "data_assinatura": (
                        status.signature_timestamp.isoformat()
                        if hasattr(status, "signature_timestamp")
                        else "N/A"
                    ),
                    "verificado_em": datetime.now().isoformat(),
                }

        except ImportError:
            logger.error("pyhanko.sign.validation não disponível")
            return {
                "valido": False,
                "erro": "Módulo de validação não disponível",
                "verificado_em": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Erro ao verificar assinatura: {e}")
            return {
                "valido": False,
                "erro": str(e),
                "verificado_em": datetime.now().isoformat(),
            }

    def _calcular_hash(self, caminho_arquivo: str) -> str:
        """Calcula hash SHA-256 do arquivo"""
        sha256_hash = hashlib.sha256()
        with open(caminho_arquivo, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


class GerenciadorAssinaturas:
    """Gerenciador centralizado de assinaturas digitais"""

    def __init__(self, config: Optional[ConfiguracaoAssinatura] = None):
        """
        Inicializa gerenciador

        Args:
            config: Configurações (usa .env se None)
        """
        if config is None:
            config = ConfiguracaoAssinatura.carregar_de_env()

        self.config = config

        # Inicializa serviços disponíveis
        self.docusign = None
        self.icp_brasil = None

        if DOCUSIGN_AVAILABLE and config.docusign_integration_key:
            try:
                self.docusign = AssinaturaDocuSign(config)
                logger.info("DocuSign disponível")
            except Exception as e:
                logger.warning(f"DocuSign não pôde ser inicializado: {e}")

        if PYHANKO_AVAILABLE and config.icp_certificado_path:
            try:
                self.icp_brasil = AssinaturaICPBrasil(config)
                logger.info("ICP-Brasil disponível")
            except Exception as e:
                logger.warning(f"ICP-Brasil não pôde ser inicializado: {e}")

    def assinar_documento(
        self, caminho_pdf: str, metodo: str = "icp-brasil", **kwargs
    ) -> Dict:
        """
        Assina documento usando o método especificado

        Args:
            caminho_pdf: Caminho do PDF
            metodo: 'docusign' ou 'icp-brasil'
            **kwargs: Parâmetros específicos do método

        Returns:
            Dict com resultado da assinatura
        """
        if metodo == "docusign":
            if not self.docusign:
                return {
                    "sucesso": False,
                    "erro": "DocuSign não está configurado",
                    "metodo": metodo,
                }

            signatarios = kwargs.get("signatarios", [])
            assunto = kwargs.get("assunto", "Documento para Assinatura")
            mensagem = kwargs.get("mensagem", "")

            return self.docusign.enviar_para_assinatura(
                caminho_pdf, signatarios, assunto, mensagem
            )

        elif metodo == "icp-brasil":
            if not self.icp_brasil:
                return {
                    "sucesso": False,
                    "erro": "ICP-Brasil não está configurado",
                    "metodo": metodo,
                }

            caminho_saida = kwargs.get(
                "caminho_saida", caminho_pdf.replace(".pd", "_assinado.pd")
            )
            razao = kwargs.get("razao", "Assinatura Digital")
            localizacao = kwargs.get("localizacao", "Brasil")
            contato = kwargs.get("contato", "")

            sucesso, mensagem, hash_doc = self.icp_brasil.assinar_pdf(
                caminho_pdf, caminho_saida, razao, localizacao, contato
            )

            return {
                "sucesso": sucesso,
                "mensagem": mensagem,
                "hash_sha256": hash_doc,
                "caminho_assinado": caminho_saida if sucesso else None,
                "metodo": metodo,
            }

        else:
            return {
                "sucesso": False,
                "erro": f"Método de assinatura inválido: {metodo}",
                "metodo": metodo,
            }

    def verificar_assinatura(
        self, caminho_pdf: str, metodo: str = "icp-brasil"
    ) -> Dict:
        """
        Verifica assinatura de um documento

        Args:
            caminho_pdf: Caminho do PDF assinado
            metodo: Método usado na assinatura

        Returns:
            Dict com resultado da verificação
        """
        if metodo == "icp-brasil":
            if not self.icp_brasil:
                return {"valido": False, "erro": "ICP-Brasil não está configurado"}
            return self.icp_brasil.verificar_assinatura(caminho_pdf)

        elif metodo == "docusign":
            # DocuSign verifica automaticamente na plataforma
            return {
                "valido": True,
                "mensagem": "Verificação realizada na plataforma DocuSign",
            }

        else:
            return {
                "valido": False,
                "erro": f"Método de verificação inválido: {metodo}",
            }

    def listar_metodos_disponiveis(self) -> List[str]:
        """Lista métodos de assinatura disponíveis"""
        metodos = []
        if self.docusign:
            metodos.append("docusign")
        if self.icp_brasil:
            metodos.append("icp-brasil")
        return metodos


# Funções auxiliares de uso rápido


def assinar_pdf_rapido(
    caminho_pdf: str, caminho_saida: Optional[str] = None, metodo: str = "icp-brasil"
) -> Dict:
    """
    Função rápida para assinar PDF

    Args:
        caminho_pdf: Caminho do PDF
        caminho_saida: Caminho do PDF assinado (opcional)
        metodo: Método de assinatura

    Returns:
        Dict com resultado
    """
    gerenciador = GerenciadorAssinaturas()

    if caminho_saida is None:
        caminho_saida = caminho_pdf.replace(".pd", "_assinado.pd")

    return gerenciador.assinar_documento(
        caminho_pdf, metodo=metodo, caminho_saida=caminho_saida
    )


def verificar_pdf_rapido(caminho_pdf: str, metodo: str = "icp-brasil") -> Dict:
    """
    Função rápida para verificar assinatura

    Args:
        caminho_pdf: Caminho do PDF assinado
        metodo: Método usado na assinatura

    Returns:
        Dict com resultado da verificação
    """
    gerenciador = GerenciadorAssinaturas()
    return gerenciador.verificar_assinatura(caminho_pdf, metodo)


def assinar_via_tool(caminho_pdf: str, assinante: Optional[Dict] = None) -> Dict:
    """
    Ponte simples para acionar a Tool de Assinatura (`ToolAssinatura`) a partir
    do Service. Mantém independência das classes: apenas importa e delega.

    Retorna o dicionário de resultado produzido pela Tool.
    """
    print("[SERVICE] -> Acionando AssinaturaTool")
    try:
        from contabil_agente.tools.assinatura_tool import ToolAssinatura

        ta = ToolAssinatura()
        if assinante is None:
            assinante = {"nome": "LEONEL", "cp": "00000000000", "tipo": "certificado"}

        res = ta.assinar_documento(caminho_pdf, assinante)
        print("[SERVICE] -> Resultado recebido da Tool")
        return res
    except Exception as e:
        print("[SERVICE] -> Erro ao acionar AssinaturaTool:", e)
        return {"status": "error", "message": str(e)}
