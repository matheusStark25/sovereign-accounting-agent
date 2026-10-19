"""Base legal do tratamento (LGPD, art. 7) e registro de finalidades.

Todo tratamento de dados pessoais tem de ter uma finalidade cadastrada e a base legal dela. Quando a
base é o CONSENTIMENTO, o tratamento só é permitido se houver consentimento ativo (veja ``consentimento``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class BaseLegal(Enum):
    CONSENTIMENTO = "art. 7º, I - consentimento do titular"
    OBRIGACAO_LEGAL = "art. 7º, II - cumprimento de obrigação legal ou regulatória"
    POLITICAS_PUBLICAS = "art. 7º, III - execução de políticas públicas"
    ESTUDOS = "art. 7º, IV - estudos por órgão de pesquisa"
    CONTRATO = "art. 7º, V - execução de contrato ou procedimentos preliminares"
    EXERCICIO_DE_DIREITOS = "art. 7º, VI - exercício regular de direitos em processo"
    PROTECAO_DA_VIDA = "art. 7º, VII - proteção da vida ou da incolumidade física"
    TUTELA_DA_SAUDE = "art. 7º, VIII - tutela da saúde"
    LEGITIMO_INTERESSE = "art. 7º, IX - legítimo interesse do controlador ou de terceiro"
    PROTECAO_DO_CREDITO = "art. 7º, X - proteção do crédito"


class TratamentoSemBaseLegal(PermissionError):
    """O tratamento foi recusado: finalidade não cadastrada ou consentimento exigido e ausente."""


@dataclass(frozen=True)
class Finalidade:
    codigo: str
    descricao: str
    base: BaseLegal
    dados_sensiveis: bool = False  # art. 11 (saúde, biometria...): base mais restrita


FINALIDADES: Dict[str, Finalidade] = {f.codigo: f for f in [
    Finalidade("calculo_trabalhista", "Calcular rescisão, férias, 13º, folha e encargos para o empregador", BaseLegal.CONTRATO),
    Finalidade("processamento_de_documentos", "Classificar, extrair e conferir documentos trabalhistas e fiscais", BaseLegal.OBRIGACAO_LEGAL),
    Finalidade("arquivamento_obrigatorio", "Guardar documentos pelo prazo legal (CLT, FGTS, previdência, fisco)", BaseLegal.OBRIGACAO_LEGAL),
    Finalidade("assistente_de_chat", "Atendimento ao operador por chat", BaseLegal.CONTRATO),
    Finalidade("auditoria_e_seguranca", "Trilha de auditoria e prevenção a fraude", BaseLegal.LEGITIMO_INTERESSE),
    Finalidade("envio_a_provedor_de_ia", "Enviar texto de documentos a provedores externos de IA (transferência a terceiros)", BaseLegal.CONSENTIMENTO),
    Finalidade("consulta_extrato_fgts", "Consultar o extrato do FGTS do trabalhador no portal da Caixa", BaseLegal.CONSENTIMENTO),
    Finalidade("consulta_extrato_pgmei", "Consultar o extrato/DAS do MEI do cliente no portal da Receita Federal", BaseLegal.CONTRATO),
    Finalidade("exame_ocupacional", "Registrar ASO e dados de saúde ocupacional", BaseLegal.OBRIGACAO_LEGAL, dados_sensiveis=True),
]}


def finalidade(codigo: str) -> Finalidade:
    f = FINALIDADES.get(codigo)
    if f is None:
        raise TratamentoSemBaseLegal(f"Finalidade não cadastrada: {codigo!r}. Cadastre a finalidade e a base legal antes de tratar dados pessoais.")
    return f


def exige_consentimento(codigo: str) -> bool:
    return finalidade(codigo).base is BaseLegal.CONSENTIMENTO


def descricao_da_base(codigo: str, extra: Optional[Dict[str, Finalidade]] = None) -> str:
    return finalidade(codigo).base.value
