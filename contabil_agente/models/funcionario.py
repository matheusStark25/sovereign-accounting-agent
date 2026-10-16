from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DadosFuncionario:
    nome: str = ""
    cpf: str = ""
    pis: str = ""
    cargo: str = ""
    salario_base: Decimal = Decimal("0.00")
    periculosidade: bool = False
    horas_extras: Decimal = Decimal("0.00")
    media_horas_extras: Decimal = Decimal("0.00")
    data_admissao: str = ""
    data_demissao: str = ""
    dependentes_irrf: int = 0
    vale_transporte: bool = False
    valor_vt: Decimal = Decimal("0.00")
    desconto_vt: Decimal = Decimal("0.00")
    vale_refeicao: bool = False
    valor_vr: Decimal = Decimal("0.00")
    desconto_vr: Decimal = Decimal("0.00")
    adicional_noturno: bool = False
    valor_adicional_noturno: Decimal = Decimal("0.00")
    insalubridade_grau: str = ""
    valor_insalubridade: Decimal = Decimal("0.00")


@dataclass
class DadosRescisaoCalculo:
    tipo: str = "sem_justa_causa"
    aviso_previo_trabalhado: bool = False
    dias_aviso_previo: int = 30
    ferias_vencidas: int = 0
    ferias_proporcionais: bool = True
    decimo_terceiro_proporcional: bool = True
    calcular_multa_fgts: bool = True
    dias_trabalhados_mes: int = 15
    possui_ferias_vencidas: bool = False
    numero_dependentes_irrf: int = 0
    pensao_alimenticia: Decimal = Decimal("0.00")
    outras_deducoes: Decimal = Decimal("0.00")
    meses_trabalhados_ano: int = 0
    meses_trabalhados_periodo_aquisitivo: int = 0
    meses_trabalhados_total: int = 0
    saldo_fgts_atual: Decimal = Decimal("0.00")
