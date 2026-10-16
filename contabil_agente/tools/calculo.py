"""Compatibilidade: ``ToolCalculo`` vive em ``calculo_tool`` e usa o motor ``contabil_agente.calc``."""

from .calculo_tool import DadosFuncionario, DadosRescisaoCalculo, ToolCalculo

__all__ = ["ToolCalculo", "DadosFuncionario", "DadosRescisaoCalculo"]
