"""
Tools - Ferramentas especializadas do sistema
Cada ferramenta é uma classe independente com responsabilidade única
"""

from .admissao_tool import ToolAdmissao
from .assinatura_tool import ToolAssinatura
from ..models.funcionario import DadosFuncionario, DadosRescisaoCalculo
from .calculo_tool import ToolCalculo
from .encargos_tool import ToolEncargosPatronais
from .gps_tool import ToolGPS
from .prolabore_tool import ToolProLabore
from .voz_tool import ToolVoz

__all__ = [
    # Cálculos e dataclasses
    "ToolCalculo",
    "DadosFuncionario",
    "DadosRescisaoCalculo",
    # Documentos
    "ToolPD",
    "ToolAssinatura",
    # Comunicação
    "ToolVoz",
    # Tributos e encargos
    "ToolEncargosPatronais",
    "ToolProLabore",
    "ToolGPS",
    "ToolDAR",
    # Processos
    "ToolAdmissao",
]
