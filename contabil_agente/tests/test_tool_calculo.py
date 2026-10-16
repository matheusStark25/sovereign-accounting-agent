"""ToolCalculo é só uma fachada: os números têm que ser os do motor ``calc``."""

from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.calc import CompetenciaSemTabela
from contabil_agente.models.funcionario import DadosFuncionario, DadosRescisaoCalculo
from contabil_agente.tools.calculo_tool import ToolCalculo

HOJE = date(2026, 9, 20)


@pytest.fixture()
def tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # a auditoria local escreve em ./.sovereign_data
    return ToolCalculo(hoje=HOJE)


def test_inss_3000_em_2026(tool):
    # 1621*7,5% + (2902,84-1621)*9% + (3000-2902,84)*12% = 121,575 + 115,3656 + 11,6592
    assert tool.calcular_inss(Decimal("3000")) == Decimal("248.60")


def test_inss_acima_do_teto_usa_o_teto(tool):
    assert tool.calcular_inss(Decimal("50000")) == tool.calcular_inss(Decimal("8475.55"))


def test_competencia_sem_tabela_nao_estima(tool):
    with pytest.raises(CompetenciaSemTabela):
        tool.calcular_inss(Decimal("3000"), competencia="2030-01-01")


def test_irrf_ate_5000_com_reducao_zera_o_imposto(tool):
    assert tool.calcular_irrf(Decimal("4000")) == Decimal("0.00")


def test_irrf_acima_da_faixa_de_reducao(tool):
    assert tool.calcular_irrf(Decimal("9000")) > Decimal("1000")


def test_executar_liquido_simples(tool):
    r = tool.executar({"salario_bruto": 3000})
    assert r["status"] == "success"
    assert r["inss"] == 248.60
    assert r["irrf"] == 0.0
    assert r["salario_liquido"] == 2751.40


def test_executar_sem_salario_pede_o_dado(tool):
    r = tool.executar({})
    assert r["status"] == "error"
    assert r["codigo"] == "faltam_dados"


def test_executar_rescisao_do_cenario_conferido_a_mao(tool):
    r = tool.executar(
        {
            "tipo_rescisao": "sem_justa_causa",
            "salario": 3000,
            "data_admissao": "10/03/2023",
            "data_demissao": "15/09/2026",
            "aviso_previo": "indenizado",
            "saldo_fgts": 12000,
        }
    )
    assert r["status"] == "success"
    assert r["detalhes"]["total_proventos"] == 10566.67
    assert r["detalhes"]["total_liquido"] == 10253.48
    assert r["fgts"]["multa"] == 5052.80
    assert r["fgts"]["deposito_rescisorio"] == 632.00


def test_executar_rescisao_sem_aviso_pergunta(tool):
    r = tool.executar(
        {
            "tipo_rescisao": "sem_justa_causa",
            "salario": 3000,
            "data_admissao": "10/03/2023",
            "data_demissao": "15/09/2026",
        }
    )
    assert r["status"] == "error"
    assert "aviso" in r["message"].lower()


def test_modelos_antigos_geram_o_mesmo_resultado_do_motor(tool):
    func = DadosFuncionario(
        salario_base=Decimal("3000"), data_admissao="10/03/2023", data_demissao="15/09/2026"
    )
    resc = DadosRescisaoCalculo(
        tipo="sem_justa_causa", aviso_previo_trabalhado=False, saldo_fgts_atual=Decimal("12000")
    )
    r = tool.calcular_rescisao_completa(func, resc)
    assert r["status"] == "success"
    assert r["detalhes"]["total_liquido"] == 10253.48


def test_periculosidade_soma_30_por_cento_nas_verbas(tool):
    base = DadosFuncionario(salario_base=Decimal("3000"), data_admissao="10/03/2023", data_demissao="15/09/2026")
    peri = DadosFuncionario(
        salario_base=Decimal("3000"), periculosidade=True, data_admissao="10/03/2023", data_demissao="15/09/2026"
    )
    resc = DadosRescisaoCalculo(tipo="sem_justa_causa", aviso_previo_trabalhado=False)
    r0 = tool.calcular_rescisao_completa(base, resc)
    r1 = tool.calcular_rescisao_completa(peri, resc)
    assert r1["detalhes"]["total_proventos"] > r0["detalhes"]["total_proventos"]


def test_justa_causa_sem_aviso(tool):
    func = DadosFuncionario(salario_base=Decimal("3000"), data_admissao="10/03/2023", data_demissao="15/09/2026")
    r = tool.calcular_rescisao_completa(func, DadosRescisaoCalculo(tipo="justa_causa"))
    assert r["status"] == "success"
    codigos = {v["codigo"] for v in r["verbas"]}
    assert not any("aviso" in c for c in codigos)
    assert not any("decimo" in c or "13" in c for c in codigos)


def test_tipo_invalido_vira_erro_e_nao_excecao(tool):
    func = DadosFuncionario(salario_base=Decimal("3000"), data_admissao="10/03/2023", data_demissao="15/09/2026")
    r = tool.calcular_rescisao_completa(func, DadosRescisaoCalculo(tipo="inventado"))
    assert r["status"] == "error"
