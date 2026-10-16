"""Ferramentas do agente: cálculo trabalhista (fachada do motor calc) e RPA do FGTS."""

from ..models.funcionario import DadosFuncionario, DadosRescisaoCalculo
from .calculo_tool import ToolCalculo

__all__ = ["ToolCalculo", "DadosFuncionario", "DadosRescisaoCalculo"]
