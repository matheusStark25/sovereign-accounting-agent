"""
Templates de resposta padronizados para o agente Maria Helena
Garante consistência nas respostas para cenários comuns
"""

from typing import Any, Dict


class ResponseTemplates:
    """Classe com templates de resposta padronizados"""

    @staticmethod
    def solicitacao_dados(campos: list) -> str:
        """Template para solicitar dados do usuário"""
        campos_formatados = "\n".join(f"- {campo}" for campo in campos)
        return f"Entendi! Para prosseguir, preciso dos seguintes dados:\n{campos_formatados}\n\nPode me fornecer essas informações?"

    @staticmethod
    def confirmacao_acao(acao: str, dados: Dict[str, Any]) -> str:
        """Template para confirmar uma ação antes de executá-la"""
        dados_formatados = "\n".join(f"- **{k}**: {v}" for k, v in dados.items())
        return f"Perfeito! Antes de {acao}, confirme se estes dados estão corretos:\n{dados_formatados}\n\nEstá tudo certo para prosseguir?"

    @staticmethod
    def geracao_documento(tipo: str) -> str:
        """Template para informar geração de documento"""
        return f"Documento gerado com sucesso! O {tipo} está pronto para download. Você pode visualizá-lo clicando no link abaixo."

    @staticmethod
    def erro_validacao(campo: str, motivo: str) -> str:
        """Template para erro de validação"""
        return f"Houve um problema com o campo **{campo}**: {motivo}. Por favor, verifique e forneça novamente."


# Instância global
response_templates = ResponseTemplates()
