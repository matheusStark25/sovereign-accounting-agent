"""Rescisão: cada cenário tem a conta feita à mão nos comentários."""

import json
from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.calc import CompetenciaSemTabela, DadosInvalidos, TipoNaoSuportado
from contabil_agente.calc.rescisao import DadosRescisao, calcular_rescisao, dados_de_dict

D = Decimal
ADM = date(2023, 3, 10)
DEM = date(2026, 9, 15)


def base(**kw):
    dados = dict(
        tipo="sem_justa_causa",
        data_admissao=ADM,
        data_demissao=DEM,
        salario_base="3000",
        aviso_previo="indenizado",
        saldo_fgts="12000",
    )
    dados.update(kw)
    return DadosRescisao(**dados)


def verba(res, codigo):
    return next(v for v in res.verbas if v.codigo == codigo).valor


def desconto(res, codigo):
    return next(d for d in res.descontos if d.codigo == codigo).valor


def test_sem_justa_causa_aviso_indenizado():
    r = calcular_rescisao(base())
    # saldo: 3.000 / 30 x 15 dias = 1.500,00
    assert verba(r, "saldo_salario") == D("1500.00")
    # aviso: 3 anos completos -> 30 + 9 = 39 dias -> 3.000 / 30 x 39 = 3.900,00
    assert r.datas["dias_aviso_total"] == 39
    assert verba(r, "aviso_previo") == D("3900.00")
    # projeção: 15/09/2026 + 39 dias = 24/10/2026
    assert r.datas["fim_projetado"] == date(2026, 10, 24)
    # 13º: janeiro a outubro (outubro com 24 dias) = 10/12 -> 3.000 / 12 x 10 = 2.500,00
    assert verba(r, "decimo_terceiro") == D("2500.00")
    # férias: período desde 10/03/2026 até 24/10/2026 = 7 meses + 15 dias = 8/12 -> 2.000,00 + 1/3 (666,67)
    assert verba(r, "ferias_proporcionais") == D("2000.00")
    assert verba(r, "ferias_proporcionais_terco") == D("666.67")
    # proventos: 1.500 + 3.900 + 2.500 + 2.000 + 666,67 = 10.566,67
    assert r.total_proventos == D("10566.67")
    # INSS saldo: 1.500 x 7,5% = 112,50 ; IRRF saldo = 0
    assert desconto(r, "inss_saldo") == D("112.50")
    assert desconto(r, "irrf_saldo") == D("0.00")
    # INSS 13º: 121,575 + (2.500 - 1.621) x 9% (79,11) = 200,685 -> 200,69 ; IRRF 13º = 0
    assert desconto(r, "inss_13") == D("200.69")
    assert desconto(r, "irrf_13") == D("0.00")
    # descontos: 112,50 + 200,69 = 313,19 ; líquido: 10.566,67 - 313,19 = 10.253,48
    assert r.total_descontos == D("313.19")
    assert r.liquido == D("10253.48")
    # FGTS: depósito = 8% x (1.500 + 3.900 + 2.500) = 632,00 ; multa 40% x (12.000 + 632) = 5.052,80
    assert r.fgts["deposito_rescisorio"] == D("632.00")
    assert r.fgts["multa"] == D("5052.80")
    assert r.direitos["saque_fgts_percentual"] == 100
    assert r.direitos["seguro_desemprego"] is True
    assert r.pendencias == []


def test_indenizacoes_nao_sofrem_inss_nem_irrf():
    r = calcular_rescisao(base())
    por_codigo = {v.codigo: v for v in r.verbas}
    for codigo in ("aviso_previo", "ferias_proporcionais", "ferias_proporcionais_terco"):
        assert por_codigo[codigo].incide_inss is False and por_codigo[codigo].incide_irrf is False
    assert por_codigo["saldo_salario"].incide_inss and por_codigo["decimo_terceiro"].incide_inss


def test_justa_causa_so_paga_saldo_e_ferias_vencidas():
    r = calcular_rescisao(base(tipo="justa causa", aviso_previo=None))
    assert [v.codigo for v in r.verbas] == ["saldo_salario"]
    # saldo 1.500 - INSS 112,50 = 1.387,50
    assert r.liquido == D("1387.50")
    assert r.fgts["multa"] == D("0")
    assert r.direitos["saque_fgts_percentual"] == 0
    assert r.direitos["seguro_desemprego"] is False


def test_justa_causa_com_ferias_vencidas():
    r = calcular_rescisao(base(tipo="justa_causa", aviso_previo=None, periodos_ferias_vencidas=1))
    # (3.000 + 1/3 = 4.000,00) x 1 período
    assert verba(r, "ferias_vencidas") == D("4000.00")
    assert "decimo_terceiro" not in [v.codigo for v in r.verbas]
    assert "ferias_proporcionais" not in [v.codigo for v in r.verbas]


def test_pedido_de_demissao_aviso_trabalhado():
    r = calcular_rescisao(base(tipo="pedido de demissão", aviso_previo="trabalhado"))
    assert r.datas["fim_projetado"] == DEM  # sem projeção
    # 13º: janeiro a setembro (setembro com 15 dias conta) = 9/12 -> 2.250,00
    assert verba(r, "decimo_terceiro") == D("2250.00")
    # férias: 10/03 a 15/09 = 6 meses + 6 dias (não conta) = 6/12 -> 1.500,00 + 500,00
    assert verba(r, "ferias_proporcionais") == D("1500.00")
    assert verba(r, "ferias_proporcionais_terco") == D("500.00")
    # proventos: 1.500 + 2.250 + 1.500 + 500 = 5.750 ; INSS 112,50 + 13º (121,575 + 629 x 9% = 178,185 -> 178,19)
    assert r.total_proventos == D("5750.00")
    assert r.total_descontos == D("290.69")
    assert r.liquido == D("5459.31")
    assert r.fgts["multa"] == D("0")
    assert r.direitos["saque_fgts_percentual"] == 0


def test_pedido_de_demissao_aviso_nao_cumprido_desconta_um_salario():
    r = calcular_rescisao(base(tipo="pedido_demissao", aviso_previo="nao_cumprido"))
    assert desconto(r, "aviso_nao_cumprido") == D("3000.00")


def test_acordo_metade_do_aviso_multa_de_20_e_saque_de_80():
    r = calcular_rescisao(base(tipo="acordo"))
    # aviso: 39 dias, metade -> 3.000 / 30 x 39 / 2 = 1.950,00 ; projeção de 19 dias -> 04/10/2026
    assert verba(r, "aviso_previo") == D("1950.00")
    assert r.datas["fim_projetado"] == date(2026, 10, 4)
    # 13º: outubro tem 4 dias (não conta) -> 9/12 = 2.250,00 ; férias: 6 meses + 25 dias -> 7/12 = 1.750,00 + 583,33
    assert verba(r, "decimo_terceiro") == D("2250.00")
    assert verba(r, "ferias_proporcionais") == D("1750.00")
    assert verba(r, "ferias_proporcionais_terco") == D("583.33")
    # FGTS: depósito 8% x (1.500 + 1.950 + 2.250) = 456,00 ; multa 20% x (12.000 + 456) = 2.491,20
    assert r.fgts["deposito_rescisorio"] == D("456.00")
    assert r.fgts["multa"] == D("2491.20")
    assert r.direitos["saque_fgts_percentual"] == 80
    assert r.direitos["seguro_desemprego"] is False
    assert any("484-A" in a for a in r.avisos)


def test_sem_saldo_do_fgts_a_multa_vira_pendencia_e_nao_e_estimada():
    r = calcular_rescisao(base(saldo_fgts=None))
    assert r.fgts["multa"] is None
    assert any("saldo do FGTS" in p for p in r.pendencias)


def test_ferias_vencidas_normais_e_em_dobro():
    r = calcular_rescisao(base(periodos_ferias_vencidas=1, periodos_ferias_vencidas_em_dobro=1))
    assert verba(r, "ferias_vencidas") == D("4000.00")
    assert verba(r, "ferias_vencidas_dobro") == D("8000.00")


def test_dependentes_e_pensao_entram_nas_deducoes_do_irrf():
    r = calcular_rescisao(
        base(salario_base="8000", data_demissao=date(2026, 9, 30), dependentes_irrf=2, pensao_alimenticia="500")
    )
    # saldo de 30 dias = 8.000,00 ; INSS = 921,51
    assert verba(r, "saldo_salario") == D("8000.00")
    assert desconto(r, "inss_saldo") == D("921.51")
    # deduções legais: 921,51 + 2 x 189,59 + 500 = 1.800,69 -> base 6.199,31 x 27,5% - 908,73 = 796,07525
    # (sem redução: rendimento acima de 7.350) -> 796,08
    assert desconto(r, "irrf_saldo") == D("796.08")
    assert desconto(r, "pensao") == D("500.00")


def test_adicionais_e_media_de_variaveis_compoem_a_base():
    r = calcular_rescisao(base(adicionais_mensais="900", media_variaveis="300"))
    # base de aviso: 3.000 + 900 + 300 = 4.200 -> 4.200 / 30 x 39 = 5.460,00
    assert verba(r, "aviso_previo") == D("5460.00")
    # saldo usa salário + adicionais (sem a média): 3.900 / 30 x 15 = 1.950,00
    assert verba(r, "saldo_salario") == D("1950.00")


def test_resultado_e_serializavel_e_fecha_as_contas():
    r = calcular_rescisao(base())
    dados = r.to_dict()
    json.dumps(dados)  # não pode falhar
    assert dados["status"] == "success"
    assert abs(dados["total_proventos"] - sum(v["valor"] for v in dados["verbas"])) < 0.005
    assert abs(dados["total_liquido"] - (dados["total_proventos"] - dados["total_descontos"])) < 0.005
    assert dados["explicacao"] and dados["tabelas"]["inss"]


# ------------------------------------------------------------- validações
def test_demissao_antes_da_admissao():
    with pytest.raises(DadosInvalidos):
        calcular_rescisao(base(data_demissao=date(2020, 1, 1)))


def test_tipo_desconhecido():
    with pytest.raises(TipoNaoSuportado):
        calcular_rescisao(base(tipo="aposentadoria"))


def test_aviso_obrigatorio_na_dispensa_sem_justa_causa():
    with pytest.raises(DadosInvalidos):
        calcular_rescisao(base(aviso_previo=None))


def test_salario_zero_ou_invalido():
    with pytest.raises(DadosInvalidos):
        calcular_rescisao(base(salario_base="0"))
    with pytest.raises(DadosInvalidos):
        calcular_rescisao(base(salario_base="abc"))


def test_competencia_sem_tabela_nao_estima():
    with pytest.raises(CompetenciaSemTabela):
        calcular_rescisao(base(data_demissao=date(2027, 2, 10)))


def test_dados_de_dict_aceita_datas_brasileiras_e_apelidos():
    payload = {
        "tipo_rescisao": "sem justa causa",
        "admissao": "10/03/2023",
        "demissao": "15/09/2026",
        "salario": "3.000,00",
        "aviso": "indenizado",
        "saldo_fgts": 12000,
        "dependentes": 0,
    }
    r = calcular_rescisao(dados_de_dict(payload))
    assert r.liquido == D("10253.48")


def test_dados_de_dict_lista_o_que_falta():
    with pytest.raises(DadosInvalidos) as exc:
        dados_de_dict({"salario": 3000})
    assert "data de admissão" in str(exc.value) and "tipo da rescisão" in str(exc.value)
