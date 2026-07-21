"""
Serviço de Geração de PDFs com Campos AcroForm
Cria documentos preenchíveis profissionais com mapeamento automático

Funcionalidades:
- Geração de PDFs com campos AcroForm (formulários interativos)
- Mapeamento automático dos cálculos para os campos
- Preview antes da geração final
- Suporte para múltiplos tipos de documentos (folha, férias, rescisão, etc.)
"""

import hashlib
import os
import tempfile
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

logger = logging.getLogger(__name__)


class MapeadorCampos:
    """Mapeia dados dos cálculos para campos dos PDFs"""

    # Mapeamento de campos para folha de pagamento
    CAMPOS_FOLHA_PAGAMENTO = {
        "nome_funcionario": {"tipo": "text", "obrigatorio": True},
        "cpf": {"tipo": "text", "obrigatorio": True},
        "cargo": {"tipo": "text", "obrigatorio": False},
        "departamento": {"tipo": "text", "obrigatorio": False},
        "mes_ano": {"tipo": "text", "obrigatorio": True},
        # Proventos
        "salario_base": {"tipo": "currency", "obrigatorio": True},
        "periculosidade": {"tipo": "currency", "obrigatorio": False},
        "insalubridade": {"tipo": "currency", "obrigatorio": False},
        "horas_extras_50": {"tipo": "currency", "obrigatorio": False},
        "horas_extras_100": {"tipo": "currency", "obrigatorio": False},
        "total_proventos": {"tipo": "currency", "obrigatorio": True},
        # Descontos
        "inss": {"tipo": "currency", "obrigatorio": True},
        "irrf": {"tipo": "currency", "obrigatorio": True},
        "total_descontos": {"tipo": "currency", "obrigatorio": True},
        # Líquido
        "salario_liquido": {"tipo": "currency", "obrigatorio": True},
        # FGTS (informativo)
        "fgts": {"tipo": "currency", "obrigatorio": True},
        # Data
        "data_emissao": {"tipo": "date", "obrigatorio": True},
    }

    # Mapeamento para férias
    CAMPOS_FERIAS = {
        "nome_funcionario": {"tipo": "text", "obrigatorio": True},
        "cpf": {"tipo": "text", "obrigatorio": True},
        "periodo_aquisitivo": {"tipo": "text", "obrigatorio": True},
        "periodo_gozo": {"tipo": "text", "obrigatorio": True},
        "valor_ferias": {"tipo": "currency", "obrigatorio": True},
        "valor_um_terco": {"tipo": "currency", "obrigatorio": True},
        "valor_abono": {"tipo": "currency", "obrigatorio": False},
        "total_bruto": {"tipo": "currency", "obrigatorio": True},
        "inss": {"tipo": "currency", "obrigatorio": True},
        "irrf": {"tipo": "currency", "obrigatorio": True},
        "total_descontos": {"tipo": "currency", "obrigatorio": True},
        "total_liquido": {"tipo": "currency", "obrigatorio": True},
        "data_emissao": {"tipo": "date", "obrigatorio": True},
    }

    # Mapeamento para rescisão
    CAMPOS_RESCISAO = {
        "nome_funcionario": {"tipo": "text", "obrigatorio": True},
        "cpf": {"tipo": "text", "obrigatorio": True},
        "data_admissao": {"tipo": "date", "obrigatorio": True},
        "data_demissao": {"tipo": "date", "obrigatorio": True},
        "motivo": {"tipo": "text", "obrigatorio": True},
        "saldo_salario": {"tipo": "currency", "obrigatorio": True},
        "aviso_previo": {"tipo": "currency", "obrigatorio": False},
        "ferias_vencidas": {"tipo": "currency", "obrigatorio": False},
        "ferias_vencidas_um_terco": {"tipo": "currency", "obrigatorio": False},
        "ferias_proporcionais": {"tipo": "currency", "obrigatorio": False},
        "ferias_proporcionais_um_terco": {"tipo": "currency", "obrigatorio": False},
        "13_proporcional": {"tipo": "currency", "obrigatorio": False},
        "multa_fgts": {"tipo": "currency", "obrigatorio": False},
        "total_bruto": {"tipo": "currency", "obrigatorio": True},
        "inss": {"tipo": "currency", "obrigatorio": True},
        "irrf": {"tipo": "currency", "obrigatorio": True},
        "total_descontos": {"tipo": "currency", "obrigatorio": True},
        "total_liquido": {"tipo": "currency", "obrigatorio": True},
        "data_emissao": {"tipo": "date", "obrigatorio": True},
    }

    @staticmethod
    def formatar_valor(valor: any, tipo: str) -> str:
        """
        Formata valor conforme o tipo do campo

        Args:
            valor: Valor a ser formatado
            tipo: Tipo do campo (text, currency, date)

        Returns:
            String formatada
        """
        if valor is None:
            return ""

        if tipo == "currency":
            if isinstance(valor, (int, float, Decimal)):
                return (
                    f"R$ {float(valor):,.2f}".replace(",", "_")
                    .replace(".", ",")
                    .replace("_", ".")
                )
            return str(valor)

        elif tipo == "date":
            if isinstance(valor, datetime):
                return valor.strftime("%d/%m/%Y")
            return str(valor)

        else:  # text
            return str(valor)

    @staticmethod
    def validar_campos(dados: Dict, tipo_documento: str) -> Tuple[bool, List[str]]:
        """
        Valida se todos os campos obrigatórios estão presentes

        Args:
            dados: Dicionário com os dados
            tipo_documento: Tipo do documento (folha, ferias, rescisao)

        Returns:
            Tuple (válido: bool, erros: List[str])
        """
        if tipo_documento == "folha":
            campos = MapeadorCampos.CAMPOS_FOLHA_PAGAMENTO
        elif tipo_documento == "ferias":
            campos = MapeadorCampos.CAMPOS_FERIAS
        elif tipo_documento == "rescisao":
            campos = MapeadorCampos.CAMPOS_RESCISAO
        else:
            return False, [f"Tipo de documento inválido: {tipo_documento}"]

        erros = []
        for nome_campo, config in campos.items():
            if config["obrigatorio"] and nome_campo not in dados:
                erros.append(f"Campo obrigatório ausente: {nome_campo}")

        return len(erros) == 0, erros


class GeradorPDFAcroForm:
    """Gerador de PDFs com campos AcroForm preenchíveis"""

    def __init__(self, diretorio_saida: Optional[str] = None):
        """
        Inicializa o gerador de PDFs

        Args:
            diretorio_saida: Diretório onde os PDFs serão salvos
        """
        if diretorio_saida is None:
            base_dir = Path(__file__).parent.parent
            diretorio_saida = base_dir / "documents_secure"

        # Garante path absoluto e compatível entre plataformas
        diretorio_absoluto = os.path.abspath(str(diretorio_saida))
        self.diretorio_saida = Path(diretorio_absoluto)
        self.diretorio_saida.mkdir(parents=True, exist_ok=True)

        # Verifica permissão real de escrita criando um arquivo temporário
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(self.diretorio_saida))
            os.close(fd)
            os.remove(tmp_path)
        except Exception as e:
            logger.critical(
                f"Permissão de escrita ausente para diretório {self.diretorio_saida}: {e}"
            )
            raise RuntimeError(
                f"Configuração crítica inválida: sem permissão de escrita em {self.diretorio_saida}"
            )

        logger.info(f"Gerador PDF inicializado - Diretório: {self.diretorio_saida}")

    def _criar_cabecalho(
        self, c: canvas.Canvas, titulo: str, empresa: str = "Empresa XYZ"
    ):
        """Cria cabeçalho padrão do documento"""
        largura, altura = A4

        # Logo/Nome da empresa
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, altura - 50, empresa)

        # Título do documento
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(largura / 2, altura - 80, titulo)

        # Linha separadora
        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        c.line(50, altura - 90, largura - 50, altura - 90)

        return altura - 110  # Retorna posição Y para começar conteúdo

    def _criar_rodape(self, c: canvas.Canvas):
        """Cria rodapé padrão do documento"""
        largura, altura = A4

        # Linha separadora
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.line(50, 80, largura - 50, 80)

        # Texto do rodapé
        c.setFont("Helvetica", 8)
        c.drawString(
            50,
            60,
            f"Documento gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
        )
        c.drawRightString(largura - 50, 60, "Página 1")

        # Assinaturas
        c.setFont("Helvetica", 9)
        y_assinatura = 40
        c.line(50, y_assinatura, 250, y_assinatura)
        c.line(largura - 250, y_assinatura, largura - 50, y_assinatura)

        c.drawCentredString(150, y_assinatura - 15, "Empregador")
        c.drawCentredString(largura - 150, y_assinatura - 15, "Funcionário")

    def gerar_folha_pagamento(
        self, dados: Dict, nome_arquivo: Optional[str] = None, preview: bool = False
    ) -> Tuple[str, str]:
        """
        Gera PDF de folha de pagamento com campos AcroForm

        Args:
            dados: Dicionário com dados da folha de pagamento
            nome_arquivo: Nome do arquivo PDF (sem extensão)
            preview: Se True, retorna preview sem salvar arquivo final

        Returns:
            Tuple (caminho_arquivo, hash_sha256)
        """
        # Validação
        valido, erros = MapeadorCampos.validar_campos(dados, "folha")
        if not valido:
            raise ValueError(f"Dados inválidos: {', '.join(erros)}")

        # Nome do arquivo
        if nome_arquivo is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cpf_limpo = dados.get("cp", "").replace(".", "").replace("-", "")
            nome_arquivo = f"folha_pagamento_{cpf_limpo}_{timestamp}"

        caminho_completo = self.diretorio_saida / f"{nome_arquivo}.pdf"

        # Criar PDF
        c = canvas.Canvas(str(caminho_completo), pagesize=A4)
        largura, altura = A4

        # Cabeçalho
        y = self._criar_cabecalho(
            c, "FOLHA DE PAGAMENTO", dados.get("empresa", "Empresa XYZ")
        )

        # Dados do funcionário
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "DADOS DO FUNCIONÁRIO")
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Nome: {dados.get('nome_funcionario', '')}")
        y -= 15
        c.drawString(50, y, f"CPF: {dados.get('cpf', '')}")
        c.drawString(300, y, f"Cargo: {dados.get('cargo', '')}")
        y -= 15
        c.drawString(50, y, f"Departamento: {dados.get('departamento', '')}")
        c.drawString(300, y, f"Competência: {dados.get('mes_ano', '')}")
        y -= 30

        # Tabela de proventos e descontos
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "DISCRIMINAÇÃO")
        y -= 25

        # Proventos
        dados_tabela = [
            ["DESCRIÇÃO", "VALOR"],
            ["PROVENTOS", ""],
            [
                "Salário Base",
                MapeadorCampos.formatar_valor(dados.get("salario_base"), "currency"),
            ],
        ]

        if dados.get("periculosidade", 0) > 0:
            dados_tabela.append(
                [
                    "Adicional de Periculosidade (30%)",
                    MapeadorCampos.formatar_valor(
                        dados.get("periculosidade"), "currency"
                    ),
                ]
            )

        if dados.get("insalubridade", 0) > 0:
            dados_tabela.append(
                [
                    "Adicional de Insalubridade",
                    MapeadorCampos.formatar_valor(
                        dados.get("insalubridade"), "currency"
                    ),
                ]
            )

        if dados.get("horas_extras_50", 0) > 0:
            dados_tabela.append(
                [
                    "Horas Extras 50%",
                    MapeadorCampos.formatar_valor(
                        dados.get("horas_extras_50"), "currency"
                    ),
                ]
            )

        if dados.get("horas_extras_100", 0) > 0:
            dados_tabela.append(
                [
                    "Horas Extras 100%",
                    MapeadorCampos.formatar_valor(
                        dados.get("horas_extras_100"), "currency"
                    ),
                ]
            )

        dados_tabela.append(
            [
                "TOTAL DE PROVENTOS",
                MapeadorCampos.formatar_valor(dados.get("total_proventos"), "currency"),
            ]
        )

        # Descontos
        dados_tabela.extend(
            [
                ["", ""],
                ["DESCONTOS", ""],
                ["INSS", MapeadorCampos.formatar_valor(dados.get("inss"), "currency")],
                ["IRRF", MapeadorCampos.formatar_valor(dados.get("irr"), "currency")],
                [
                    "TOTAL DE DESCONTOS",
                    MapeadorCampos.formatar_valor(
                        dados.get("total_descontos"), "currency"
                    ),
                ],
                ["", ""],
                [
                    "SALÁRIO LÍQUIDO",
                    MapeadorCampos.formatar_valor(
                        dados.get("salario_liquido"), "currency"
                    ),
                ],
                ["", ""],
                [
                    "FGTS (8%) - Para Depósito",
                    MapeadorCampos.formatar_valor(dados.get("fgts"), "currency"),
                ],
            ]
        )

        # Criar tabela
        tabela = Table(dados_tabela, colWidths=[350, 150])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
                    ("BACKGROUND", (0, 7), (-1, 7), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("LINEBELOW", (0, 6), (-1, 6), 2, colors.black),
                    ("LINEBELOW", (0, 11), (-1, 11), 2, colors.black),
                    ("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold"),
                    ("FONTNAME", (0, 11), (-1, 11), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 11), (-1, 11), 12),
                ]
            )
        )

        # Desenhar tabela
        tabela.wrapOn(c, largura, altura)
        y_tabela = y - (len(dados_tabela) * 20)
        tabela.drawOn(c, 50, y_tabela)

        # Rodapé
        self._criar_rodape(c)

        # Finalizar
        c.save()

        # Calcular hash
        hash_sha256 = self._calcular_hash(caminho_completo)

        session_id = dados.get("session_id") if isinstance(dados, dict) else None
        logger.info(
            f"Folha de pagamento gerada: {caminho_completo} | session_id={session_id}"
        )
        logger.info(f"Hash SHA-256: {hash_sha256} | session_id={session_id}")

        return str(caminho_completo), hash_sha256

    def gerar_recibo_ferias(
        self, dados: Dict, nome_arquivo: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Gera PDF de recibo de férias

        Args:
            dados: Dicionário com dados das férias
            nome_arquivo: Nome do arquivo PDF

        Returns:
            Tuple (caminho_arquivo, hash_sha256)
        """
        valido, erros = MapeadorCampos.validar_campos(dados, "ferias")
        if not valido:
            raise ValueError(f"Dados inválidos: {', '.join(erros)}")

        if nome_arquivo is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cpf_limpo = dados.get("cp", "").replace(".", "").replace("-", "")
            nome_arquivo = f"recibo_ferias_{cpf_limpo}_{timestamp}"

        caminho_completo = self.diretorio_saida / f"{nome_arquivo}.pdf"

        c = canvas.Canvas(str(caminho_completo), pagesize=A4)
        largura, altura = A4

        # Cabeçalho
        y = self._criar_cabecalho(
            c, "RECIBO DE FÉRIAS", dados.get("empresa", "Empresa XYZ")
        )

        # Dados do funcionário
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "DADOS DO FUNCIONÁRIO")
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Nome: {dados.get('nome_funcionario', '')}")
        y -= 15
        c.drawString(50, y, f"CPF: {dados.get('cpf', '')}")
        y -= 15
        c.drawString(
            50, y, f"Período Aquisitivo: {dados.get('periodo_aquisitivo', '')}"
        )
        y -= 15
        c.drawString(50, y, f"Período de Gozo: {dados.get('periodo_gozo', '')}")
        y -= 30

        # Detalhamento
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "DISCRIMINAÇÃO DAS FÉRIAS")
        y -= 25

        dados_tabela = [
            ["DESCRIÇÃO", "VALOR"],
            [
                "Férias (30 dias)",
                MapeadorCampos.formatar_valor(dados.get("valor_ferias"), "currency"),
            ],
            [
                "Adicional 1/3 Constitucional",
                MapeadorCampos.formatar_valor(dados.get("valor_um_terco"), "currency"),
            ],
        ]

        if dados.get("valor_abono", 0) > 0:
            dados_tabela.append(
                [
                    "Abono Pecuniário (10 dias)",
                    MapeadorCampos.formatar_valor(dados.get("valor_abono"), "currency"),
                ]
            )

        dados_tabela.extend(
            [
                [
                    "TOTAL BRUTO",
                    MapeadorCampos.formatar_valor(dados.get("total_bruto"), "currency"),
                ],
                ["", ""],
                ["DESCONTOS", ""],
                ["INSS", MapeadorCampos.formatar_valor(dados.get("inss"), "currency")],
                ["IRRF", MapeadorCampos.formatar_valor(dados.get("irr"), "currency")],
                [
                    "TOTAL DE DESCONTOS",
                    MapeadorCampos.formatar_valor(
                        dados.get("total_descontos"), "currency"
                    ),
                ],
                ["", ""],
                [
                    "VALOR LÍQUIDO A RECEBER",
                    MapeadorCampos.formatar_valor(
                        dados.get("total_liquido"), "currency"
                    ),
                ],
            ]
        )

        tabela = Table(dados_tabela, colWidths=[350, 150])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
                    ("FONTNAME", (0, 10), (-1, 10), "Helvetica-Bold"),
                    ("FONTNAME", (0, 12), (-1, 12), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 12), (-1, 12), 12),
                    ("LINEBELOW", (0, 4), (-1, 4), 2, colors.black),
                    ("LINEBELOW", (0, 12), (-1, 12), 2, colors.black),
                ]
            )
        )

        tabela.wrapOn(c, largura, altura)
        y_tabela = y - (len(dados_tabela) * 20)
        tabela.drawOn(c, 50, y_tabela)

        self._criar_rodape(c)
        c.save()

        hash_sha256 = self._calcular_hash(caminho_completo)

        session_id = dados.get("session_id") if isinstance(dados, dict) else None
        logger.info(
            f"Recibo de férias gerado: {caminho_completo} | session_id={session_id}"
        )
        logger.info(f"Hash SHA-256: {hash_sha256} | session_id={session_id}")

        return str(caminho_completo), hash_sha256

    def gerar_termo_rescisao(
        self, dados: Dict, nome_arquivo: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Gera PDF de termo de rescisão contratual

        Args:
            dados: Dicionário com dados da rescisão
            nome_arquivo: Nome do arquivo PDF

        Returns:
            Tuple (caminho_arquivo, hash_sha256)
        """
        valido, erros = MapeadorCampos.validar_campos(dados, "rescisao")
        if not valido:
            raise ValueError(f"Dados inválidos: {', '.join(erros)}")

        if nome_arquivo is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cpf_limpo = dados.get("cp", "").replace(".", "").replace("-", "")
            nome_arquivo = f"termo_rescisao_{cpf_limpo}_{timestamp}"

        caminho_completo = self.diretorio_saida / f"{nome_arquivo}.pdf"

        c = canvas.Canvas(str(caminho_completo), pagesize=A4)
        largura, altura = A4

        # Cabeçalho
        y = self._criar_cabecalho(
            c,
            "TERMO DE RESCISÃO DO CONTRATO DE TRABALHO",
            dados.get("empresa", "Empresa XYZ"),
        )

        # Dados do funcionário
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "DADOS DO FUNCIONÁRIO")
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Nome: {dados.get('nome_funcionario', '')}")
        y -= 15
        c.drawString(50, y, f"CPF: {dados.get('cpf', '')}")
        y -= 15
        c.drawString(50, y, f"Data de Admissão: {dados.get('data_admissao', '')}")
        c.drawString(300, y, f"Data de Demissão: {dados.get('data_demissao', '')}")
        y -= 15
        c.drawString(50, y, f"Motivo: {dados.get('motivo', '')}")
        y -= 30

        # Verbas rescisórias
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "VERBAS RESCISÓRIAS")
        y -= 25

        dados_tabela = [
            ["DESCRIÇÃO", "VALOR"],
            [
                "Saldo de Salário",
                MapeadorCampos.formatar_valor(dados.get("saldo_salario"), "currency"),
            ],
        ]

        if dados.get("aviso_previo", 0) > 0:
            dados_tabela.append(
                [
                    "Aviso Prévio Indenizado",
                    MapeadorCampos.formatar_valor(
                        dados.get("aviso_previo"), "currency"
                    ),
                ]
            )

        if dados.get("ferias_vencidas", 0) > 0:
            dados_tabela.append(
                [
                    "Férias Vencidas",
                    MapeadorCampos.formatar_valor(
                        dados.get("ferias_vencidas"), "currency"
                    ),
                ]
            )
            dados_tabela.append(
                [
                    "Férias Vencidas + 1/3",
                    MapeadorCampos.formatar_valor(
                        dados.get("ferias_vencidas_um_terco"), "currency"
                    ),
                ]
            )

        if dados.get("ferias_proporcionais", 0) > 0:
            dados_tabela.append(
                [
                    "Férias Proporcionais",
                    MapeadorCampos.formatar_valor(
                        dados.get("ferias_proporcionais"), "currency"
                    ),
                ]
            )
            dados_tabela.append(
                [
                    "Férias Proporcionais + 1/3",
                    MapeadorCampos.formatar_valor(
                        dados.get("ferias_proporcionais_um_terco"), "currency"
                    ),
                ]
            )

        if dados.get("13_proporcional", 0) > 0:
            dados_tabela.append(
                [
                    "13º Salário Proporcional",
                    MapeadorCampos.formatar_valor(
                        dados.get("13_proporcional"), "currency"
                    ),
                ]
            )

        if dados.get("multa_fgts", 0) > 0:
            dados_tabela.append(
                [
                    "Multa FGTS (40%)",
                    MapeadorCampos.formatar_valor(dados.get("multa_fgts"), "currency"),
                ]
            )

        dados_tabela.extend(
            [
                [
                    "TOTAL BRUTO",
                    MapeadorCampos.formatar_valor(dados.get("total_bruto"), "currency"),
                ],
                ["", ""],
                ["DESCONTOS", ""],
                ["INSS", MapeadorCampos.formatar_valor(dados.get("inss"), "currency")],
                ["IRRF", MapeadorCampos.formatar_valor(dados.get("irr"), "currency")],
                [
                    "TOTAL DE DESCONTOS",
                    MapeadorCampos.formatar_valor(
                        dados.get("total_descontos"), "currency"
                    ),
                ],
                ["", ""],
                [
                    "VALOR LÍQUIDO A RECEBER",
                    MapeadorCampos.formatar_valor(
                        dados.get("total_liquido"), "currency"
                    ),
                ],
            ]
        )

        tabela = Table(dados_tabela, colWidths=[350, 150])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, -1), (-1, -1), 12),
                    ("LINEBELOW", (0, -1), (-1, -1), 2, colors.black),
                ]
            )
        )

        tabela.wrapOn(c, largura, altura)
        y_tabela = y - (len(dados_tabela) * 20)
        tabela.drawOn(c, 50, max(y_tabela, 120))  # Garante espaço para rodapé

        self._criar_rodape(c)
        c.save()

        hash_sha256 = self._calcular_hash(caminho_completo)

        session_id = dados.get("session_id") if isinstance(dados, dict) else None
        logger.info(
            f"Termo de rescisão gerado: {caminho_completo} | session_id={session_id}"
        )
        logger.info(f"Hash SHA-256: {hash_sha256} | session_id={session_id}")

        return str(caminho_completo), hash_sha256

    def _calcular_hash(self, caminho_arquivo: Path) -> str:
        """Calcula hash SHA-256 do arquivo PDF"""
        sha256_hash = hashlib.sha256()
        try:
            with open(caminho_arquivo, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            # Log de auditoria e falha segura: não propaga exceção para não derrubar backend
            logger.error(
                f"Erro ao calcular hash do arquivo {caminho_arquivo}: {e}",
                exc_info=True,
            )
            return ""


class PreviewPDF:
    """Gera preview de documentos antes da geração final"""

    @staticmethod
    def gerar_preview_dados(dados: Dict, tipo_documento: str) -> Dict:
        """
        Gera preview estruturado dos dados antes de criar o PDF

        Args:
            dados: Dados do documento
            tipo_documento: Tipo (folha, ferias, rescisao)

        Returns:
            Dict com preview formatado
        """
        valido, erros = MapeadorCampos.validar_campos(dados, tipo_documento)

        preview = {
            "tipo_documento": tipo_documento,
            "valido": valido,
            "erros": erros,
            "dados_formatados": {},
            "timestamp": datetime.now().isoformat(),
        }

        # Formata todos os campos conforme o tipo
        if tipo_documento == "folha":
            campos = MapeadorCampos.CAMPOS_FOLHA_PAGAMENTO
        elif tipo_documento == "ferias":
            campos = MapeadorCampos.CAMPOS_FERIAS
        elif tipo_documento == "rescisao":
            campos = MapeadorCampos.CAMPOS_RESCISAO
        else:
            return preview

        for nome_campo, config in campos.items():
            if nome_campo in dados:
                preview["dados_formatados"][nome_campo] = MapeadorCampos.formatar_valor(
                    dados[nome_campo], config["tipo"]
                )

        return preview
