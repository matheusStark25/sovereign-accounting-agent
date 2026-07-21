"""
Document Dispatcher - Detecção Inteligente de Intenções

Este módulo detecta automaticamente qual tipo de documento o usuário deseja
gerar baseado em palavras-chave, padrões e contexto da mensagem.

Suporta 23 tipos de documentos do Departamento Pessoal.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Optional

from ..utils.audit import send_audit


class DocumentDispatcher:
    """
    Dispatcher que detecta intenção de gerar/imprimir/criar documentos.

    Detecta automaticamente qual dos 23 tipos de documentos o usuário
    precisa e extrai dados relevantes da mensagem.

    Tipos de documentos suportados:
        - Rescisão e Desligamentos: rescisao, aviso_previo
        - Transferências: transferencia, mudanca_funcao, alteracao_salarial
        - Pagamentos: holerite, recibo, decimo_terceiro
        - Férias: ferias, abono_pecuniario
        - Contratos: contrato, ctps, ficha_registro
        - Advertências: advertencia, suspensao, termo_ajuste
        - Declarações: declaracao_vinculo, carta_referencia, atestado_trabalho
        - Acordos: acordo_compensacao
        - Benefícios: vale_transporte, plano_saude

    Exemplos:
        >>> from contabil_agente.tools import ToolPDF, ToolCalculo
        >>> dispatcher = DocumentDispatcher(ToolPDF(), ToolCalculo())
        >>>
        >>> # Detecta tipo de documento
        >>> tipo = dispatcher.detectar_intencao_documento("Gerar rescisão de João")
        >>> print(tipo)  # "rescisao"
        >>>
        >>> # Extrai dados da mensagem
        >>> dados = dispatcher.extrair_dados_documento("João, CPF 123.456.789-00, cargo Analista")
        >>> print(dados["nome"])  # "João"
        >>> print(dados["cp"])   # "123.456.789-00"
    """

    def __init__(self, tool_pdf=None, tool_calculo=None):
        """
        Inicializa o Dispatcher.

        Args:
            tool_pdf: Instância de ToolPDF (opcional)
            tool_calculo: Instância de ToolCalculo (opcional)
        """
        self.tool_pdf = tool_pdf
        self.tool_calculo = tool_calculo

        # Palavras-chave para detecção de ações
        self.intencoes_documento = {
            "gerar": ["gerar", "create", "criar", "emitir", "fazer"],
            "imprimir": ["imprimir", "print", "imprime"],
            "documento": [
                "documento",
                "termo",
                "trct",
                "holerite",
                "recibo",
                "pd",
                "contrato",
                "carta",
                "transferência",
                "transferencia",
            ],
        }

        send_audit(
            "DocumentDispatcher inicializado",
            level="info",
            context={
                "tools": {
                    "pd": tool_pdf is not None,
                    "calculo": tool_calculo is not None,
                }
            },
        )

    def detectar_intencao_documento(self, mensagem: str) -> Optional[str]:
        """
        Detecta qual tipo de documento o usuário deseja gerar.

        Analisa a mensagem e identifica padrões que indicam um dos 23 tipos
        de documentos suportados. Usa priorização (mais específico primeiro).

        Args:
            mensagem: Texto da solicitação do usuário

        Returns:
            str: Tipo de documento detectado (ex: "rescisao", "holerite")
            None: Se não detectou intenção clara

        Exemplos:
            >>> dispatcher.detectar_intencao_documento("Preciso de uma rescisão")
            "rescisao"

            >>> dispatcher.detectar_intencao_documento("Gerar holerite de Maria")
            "holerite"

            >>> dispatcher.detectar_intencao_documento("João vai transferir de posto")
            "transferencia"
        """
        if not mensagem:
            return None

        msg_lower = mensagem.lower()

        # MAPEAMENTO COMPLETO: palavra-chave → tipo de documento
        # Ordem IMPORTA: mais específico primeiro!
        mapa_documentos = {
            # Rescisão e desligamentos
            "rescisao": [
                "rescisão",
                "rescisao",
                "demissão",
                "demissao",
                "trct",
                "desligar",
                "desligamento",
                "sair da empresa",
                "saiu",
                "vai sair",
            ],
            "aviso_previo": ["aviso prévio", "aviso previo", "aviso"],
            # Transferências e mudanças
            "transferencia": [
                "transferir",
                "transferência",
                "transferencia",
                "trocar de posto",
                "trocar posto",
                "mudar de filial",
                "mudar filial",
                "mudança de local",
                "outro posto",
            ],
            "mudanca_funcao": [
                "mudança de função",
                "mudanca de funcao",
                "mudar de cargo",
                "trocar de cargo",
                "promover",
                "promoção",
                "promocao",
            ],
            "alteracao_salarial": [
                "alteração salarial",
                "alteracao salarial",
                "aumento de salário",
                "aumento salarial",
                "ajuste salarial",
                "reajuste",
            ],
            # Pagamentos
            "holerite": [
                "holerite",
                "contracheque",
                "folha de pagamento",
                "folha",
                "demonstrativo",
            ],
            "recibo": ["recibo", "comprovante de pagamento"],
            "decimo_terceiro": [
                "13º",
                "13",
                "décimo terceiro",
                "decimo terceiro",
                "gratificação natalina",
            ],
            # Férias
            "ferias": ["férias", "ferias", "período de férias", "tirar férias"],
            "abono_pecuniario": [
                "abono pecuniário",
                "abono pecuniario",
                "vender férias",
                "converter férias",
            ],
            # Contratos e admissões
            "contrato": [
                "contrato",
                "contratar",
                "contratação",
                "contratacao",
                "admitir",
                "admissão",
                "admissao",
            ],
            "ctps": [
                "ctps",
                "carteira de trabalho",
                "anotação ctps",
                "anotar carteira",
            ],
            "ficha_registro": [
                "ficha de registro",
                "ficha registro",
                "cadastro funcionário",
            ],
            # Advertências e punições
            "advertencia": [
                "advertência",
                "advertencia",
                "advertir",
                "notificação",
                "notificacao",
            ],
            "suspensao": [
                "suspensão",
                "suspensao",
                "suspender",
                "afastamento disciplinar",
            ],
            "termo_ajuste": ["termo de ajuste", "ajuste de conduta", "acordo"],
            # Declarações e atestados
            "declaracao_vinculo": [
                "declaração de vínculo",
                "declaracao de vinculo",
                "declaração vínculo",
                "comprovante de vínculo",
            ],
            "carta_referencia": [
                "carta de referência",
                "carta de referencia",
                "referência profissional",
            ],
            "atestado_trabalho": [
                "atestado de trabalho",
                "atestado trabalho",
                "comprovante de trabalho",
            ],
            # Acordos e jornada
            "acordo_compensacao": [
                "acordo de compensação",
                "acordo de compensacao",
                "compensação de horas",
                "banco de horas",
            ],
            # Benefícios
            "vale_transporte": [
                "vale transporte",
                "vale-transporte",
                "vt",
                "auxílio transporte",
            ],
            "plano_saude": [
                "plano de saúde",
                "plano saude",
                "convênio médico",
                "convenio medico",
            ],
        }

        # Detecta qual documento o usuário quer (PRIORIZA mais específico)
        for tipo_doc, palavras_chave in mapa_documentos.items():
            if any(palavra in msg_lower for palavra in palavras_chave):
                send_audit(
                    f"Intenção detectada: {tipo_doc}",
                    level="info",
                    context={"mensagem": mensagem[:100], "tipo": tipo_doc},
                )
                return tipo_doc

        # Fallback: se tem ação genérica + nome, tenta inferir contexto
        actions = ["gerar", "criar", "fazer", "emitir", "imprimir", "preciso"]
        has_action = any(a in msg_lower for a in actions)

        # Detecta nome próprio
        name_match = re.search(
            r"\b([A-ZÀ-Ú][a-zà-ú -]+(?:\s+[A-ZÀ-Ú][a-zà-ú -]+)*)\b", mensagem
        )
        name_field = re.search(
            r"(?:nome|colaborador|funcionário|funcionario|func)[:\s]+([A-Za-zÀ-ú\s]+?)(?:,|\.|$)",
            mensagem,
            re.IGNORECASE,
        )

        if has_action and (name_match or name_field):
            # Se mencionou "documento" genérico + tem nome, assume contrato (mais comum)
            if "documento" in msg_lower or "carta" in msg_lower:
                send_audit(
                    "Intenção inferida: contrato (fallback genérico)",
                    level="info",
                    context={"mensagem": mensagem[:100]},
                )
                return "contrato"

        send_audit(
            "Nenhuma intenção de documento detectada",
            level="info",
            context={"mensagem": mensagem[:100]},
        )
        return None

    def extrair_dados_documento(self, mensagem: str) -> Dict[str, str]:
        """
        Extrai dados estruturados da mensagem do usuário.

        Identifica automaticamente:
        - Nome do funcionário
        - CPF (formato XXX.XXX.XXX-XX ou 11 dígitos)
        - Cargo/função
        - Salário (R$ ou valor numérico)
        - Locais (para transferências: "de X para Y")

        Args:
            mensagem: Texto da solicitação do usuário

        Returns:
            Dict com chaves: nome, cpf, cargo, salario, local_atual, local_novo
            Campos não encontrados retornam string vazia ou "0.00" (salário)

        Exemplos:
            >>> dados = dispatcher.extrair_dados_documento(
            ...     "João Silva, CPF 123.456.789-00, cargo Analista, salário R$ 5000"
            ... )
            >>> print(dados)
            {
                "nome": "João Silva",
                "cp": "123.456.789-00",
                "cargo": "Analista",
                "salario": "5000.00",
                "local_atual": "",
                "local_novo": ""
            }

            >>> dados = dispatcher.extrair_dados_documento(
            ...     "Ramiro vai transferir de posto A para posto B"
            ... )
            >>> print(dados["local_atual"])  # "Posto A"
            >>> print(dados["local_novo"])   # "Posto B"
        """
        msg_lower = mensagem.lower()

        dados = {
            "nome": "",
            "cp": "",
            "cargo": "",
            "salario": "0.00",
            "local_atual": "",
            "local_novo": "",
        }

        # Nome (aceita várias notações)
        match_nome = re.search(
            r"(?:nome|colaborador|funcionário|funcionario|func)[:\s]+([a-záéíóú âãêô\s]+?)(?:\s*,|\s*\.|cpf|cargo|vai|$)",
            msg_lower,
        )
        if not match_nome:
            # Tenta pegar nome próprio (ex: "Ramiro vai transferir")
            match_nome = re.search(
                r"\b([A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ][a-záéíóú âãêô]+(?:\s+[A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ][a-záéíóú âãêô]+)*)\s+(?:vai|vair|esta|está|precisa)",
                mensagem,
            )

        if not match_nome:
            # Última tentativa: resposta curta com apenas um nome (ex: "RAMIRO")
            palavras = mensagem.strip().split()
            if len(palavras) <= 3:  # Resposta curta
                for palavra in palavras:
                    if len(palavra) >= 3 and palavra[0].isupper():
                        # Provavelmente é um nome
                        match_nome = re.match(
                            r"[A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ][a-záéíóúàâãêôç]+", palavra
                        )
                        if match_nome:
                            break

        if match_nome:
            nome_extraido = (
                match_nome.group(0)
                if isinstance(match_nome.group(0), str)
                else match_nome.group(1)
            )
            dados["nome"] = nome_extraido.strip().title()

        # CPF (padrão XXX.XXX.XXX-XX ou números)
        match_cpf = re.search(r"(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})", mensagem)
        if match_cpf:
            dados["cp"] = match_cpf.group(1)

        # Cargo (busca "cargo: X")
        match_cargo = re.search(
            r"(?:cargo|função|funcao)[:\s]+([a-záéíóúàâãêôç\s]+?)(?:\s*,|\s*\.|salário|salario|$)",
            msg_lower,
        )
        if match_cargo:
            dados["cargo"] = match_cargo.group(1).strip().title()

        # Salário
        match_sal = re.search(
            r"(?:salário|salario|sal|r\$)[:\s]*(?:r\$)?\s*([\d\.,]+)", msg_lower
        )
        if match_sal:
            valor_str = match_sal.group(1).replace(".", "").replace(",", ".")
            try:
                dec_sal = Decimal(valor_str).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                dados["salario"] = f"{dec_sal:.2f}"
            except Exception:
                dados["salario"] = "0.00"

        # Locais (para transferências)
        # Detecta "de X para Y" ou "posto atual X para Y"
        match_transferencia = re.search(
            r"(?:de|posto|filial)\s+([a-záéíóú âãêô\s]+?)\s+(?:para|pra|p)\s+([a-záéíóú âãêô\s]+?)(?:\s|$|,|\.)",
            msg_lower,
        )
        if match_transferencia:
            dados["local_atual"] = match_transferencia.group(1).strip().title()
            dados["local_novo"] = match_transferencia.group(2).strip().title()
        else:
            # Tenta "para outro posto" ou "pro posto X"
            match_outro = re.search(
                r"(?:para|pra|pro)\s+(?:outro|outra|o)?\s*posto\s+([a-záéíóú âãêô\s]+?)(?:\s|$|,|\.)",
                msg_lower,
            )
            if match_outro:
                dados["local_novo"] = match_outro.group(1).strip().title()
            else:
                # Última tentativa: só "posto X" em resposta curta
                match_simples = re.search(
                    r"\bposto\s+([a-záéíóú âãêô\s]{3,})(?:\s|$)", msg_lower
                )
                if match_simples:
                    dados["local_novo"] = match_simples.group(1).strip().title()

        send_audit(
            "Dados extraídos da mensagem",
            level="info",
            context={
                "mensagem": mensagem[:100],
                "dados_extraidos": {k: v for k, v in dados.items() if v},
            },
        )

        return dados

    def eh_intencao_documento(self, mensagem: str) -> bool:
        """
        Verifica rapidamente se a mensagem tem intenção de gerar documento.

        Args:
            mensagem: Texto do usuário

        Returns:
            bool: True se detectou intenção, False caso contrário

        Exemplos:
            >>> dispatcher.eh_intencao_documento("Gerar rescisão")
            True

            >>> dispatcher.eh_intencao_documento("Como vai?")
            False
        """
        intencao = self.detectar_intencao_documento(mensagem)
        return intencao is not None
