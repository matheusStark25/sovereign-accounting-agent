from datetime import date

from contabil_agente.intelligence.dialogo_calculo import DialogoCalculo

HOJE = date(2026, 10, 15)


def novo():
    return DialogoCalculo(hoje=HOJE), {}


def test_mensagem_que_nao_e_de_calculo_passa_adiante():
    d, estado = novo()
    assert d.processar(estado, "oi, tudo bem?") is None
    assert d.processar(estado, "quero gerar um documento de admissão") is None


def test_inss_em_uma_frase_usa_o_motor_real():
    d, estado = novo()
    r = d.processar(estado, "Calcular o INSS de um salário de R$ 5.000,00")
    assert r["status"] == "ok" and r["tipo"] == "inss"
    assert r["dados_calculados"]["inss"] == 501.51  # conta oficial 2026, nunca o salário devolvido
    assert "R$ 501,51" in r["resposta"]


def test_ferias_de_30_dias():
    d, estado = novo()
    r = d.processar(estado, "Calcule minhas férias, salário 3000, 30 dias")
    assert r["status"] == "ok"
    assert r["dados_calculados"]["total_bruto"] == 4000.00  # 3.000 + 1/3
    assert r["dados_calculados"]["inss"] == 368.60


def test_13o_pergunta_os_meses_e_depois_calcula():
    d, estado = novo()
    r1 = d.processar(estado, "quanto fica meu 13º com salário de 3000?")
    assert r1["status"] == "aguardando_dados" and "meses" in r1["resposta"].lower()
    r2 = d.processar(estado, "8")
    assert r2["status"] == "ok"
    assert r2["dados_calculados"]["total_bruto"] == 2000.00  # 3.000 / 12 x 8
    assert "calculo" not in estado  # diálogo encerrado


def test_rescisao_em_varias_mensagens():
    d, estado = novo()
    r = d.processar(estado, "preciso calcular a rescisão do João")
    assert r["status"] == "aguardando_dados" and "salário" in r["resposta"]
    r = d.processar(estado, "3000")
    assert r["status"] == "aguardando_dados"
    r = d.processar(estado, "foi demitido sem justa causa")
    assert r["status"] == "aguardando_dados" and "admiss" in r["resposta"].lower()
    r = d.processar(estado, "10/03/2023")
    assert r["status"] == "aguardando_dados" and "demiss" in r["resposta"].lower()
    r = d.processar(estado, "15/09/2026")
    assert r["status"] == "aguardando_dados" and "aviso" in r["resposta"].lower()
    r = d.processar(estado, "indenizado")
    assert r["status"] == "aguardando_dados" and "FGTS" in r["resposta"]
    r = d.processar(estado, "12.000,00")
    assert r["status"] == "ok" and r["tipo"] == "rescisao"
    dados = r["dados_calculados"]
    assert dados["total_liquido"] == 10253.48
    assert dados["fgts"]["multa"] == 5052.80
    assert "Líquido a receber: R$ 10.253,48" in r["resposta"]
    assert estado["ultimo_calculo"]["tipo"] == "rescisao"


def test_rescisao_completa_em_uma_unica_mensagem():
    d, estado = novo()
    r = d.processar(
        estado,
        "Calcular rescisão sem justa causa, salário de R$ 3.000,00, admitido em 10/03/2023, demitido em 15/09/2026, "
        "aviso indenizado, saldo do FGTS R$ 12.000,00",
    )
    assert r["status"] == "ok"
    assert r["dados_calculados"]["total_liquido"] == 10253.48


def test_sem_saldo_do_fgts_calcula_e_deixa_pendencia():
    d, estado = novo()
    d.processar(estado, "rescisão sem justa causa salário 3000 admitido em 10/03/2023 demitido em 15/09/2026 aviso indenizado")
    r = d.processar(estado, "sem saldo")
    assert r["status"] == "ok"
    assert r["dados_calculados"]["fgts"]["multa"] is None
    assert "Pendência" in r["resposta"]


def test_pedido_de_demissao_nao_pergunta_saldo_do_fgts():
    d, estado = novo()
    r = d.processar(estado, "rescisão por pedido de demissão, salário 3000, admitido em 10/03/2023, demitido em 15/09/2026, aviso trabalhado")
    assert r["status"] == "ok"
    assert r["dados_calculados"]["total_liquido"] == 5459.31


def test_ferias_vencidas_dentro_da_rescisao_nao_troca_de_calculo():
    d, estado = novo()
    d.processar(estado, "calcular rescisão do Pedro")
    d.processar(estado, "salário 3000, justa causa, admitido em 10/03/2023, demitido em 15/09/2026")
    # a conversa seguiu; "férias vencidas" não pode virar um cálculo de férias
    assert estado.get("calculo") is None or estado["calculo"]["tipo"] == "rescisao"
    assert estado["ultimo_calculo"]["tipo"] == "rescisao"


def test_cancelar_limpa_o_estado():
    d, estado = novo()
    d.processar(estado, "calcular rescisão")
    r = d.processar(estado, "deixa pra lá, cancela")
    assert "cancelei" in r["resposta"].lower()
    assert "calculo" not in estado


def test_data_invalida_volta_a_perguntar():
    d, estado = novo()
    r = d.processar(estado, "rescisão por justa causa salário 3000 admitido em 10/03/2026 demitido em 15/09/2020")
    assert r["status"] == "erro_calculo" and "anterior" in r["resposta"]


def test_competencia_sem_tabela_explica_e_nao_estima():
    d = DialogoCalculo(hoje=date(2027, 3, 5))
    estado = {}
    r = d.processar(estado, "calcular INSS de 5000")
    assert r["status"] == "erro_calculo"
    assert "tabela" in r["resposta"].lower()
    assert "calculo" not in estado
