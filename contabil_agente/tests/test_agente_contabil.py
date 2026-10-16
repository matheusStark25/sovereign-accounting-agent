from datetime import date

from contabil_agente.agent import AgenteContabil, inferir_tipo

HOJE = date(2026, 9, 20)
RESCISAO = {
    "tipo_rescisao": "sem_justa_causa", "salario": 3000, "data_admissao": "10/03/2023",
    "data_demissao": "15/09/2026", "aviso_previo": "indenizado", "saldo_fgts": 12000,
}


def test_inferencia_do_tipo():
    assert inferir_tipo({"tipo_calculo": "ferias"}) == "ferias"
    assert inferir_tipo(RESCISAO) == "rescisao"
    assert inferir_tipo({"salario": 3000}) == "folha"


def test_pedido_completo_calcula_gera_pdf_e_assina():
    eventos = []
    agente = AgenteContabil(auditoria=lambda e, d: eventos.append((e, d)), hoje=HOJE)
    r = agente.processar_pedido(RESCISAO, contexto={"nome_funcionario": "Fulano"}, incluir_pdf=True)
    assert r["success"] and r["resultado"]["total_liquido"] == 10253.48
    assert len(r["assinatura"]["pdf_sha256"]) == 64 and r["assinatura"]["metodo"] == "sha256"
    import base64
    assert base64.b64decode(r["pdf_base64"]).startswith(b"%PDF-")
    assert [e for e, _ in eventos] == ["calculo", "pdf", "pedido_processado"]


def test_salario_bruto_antigo_continua_funcionando():
    r = AgenteContabil(hoje=HOJE).processar_pedido({"salario_bruto": 3000.0, "meses_trabalhados": 12})
    assert r["success"] and r["tipo"] == "folha" and r["resultado"]["total_liquido"] == 2751.40


def test_dado_faltando_nao_gera_pdf():
    r = AgenteContabil(hoje=HOJE).processar_pedido({"tipo_calculo": "ferias"})
    assert r["success"] is False and r["status"] == "faltam_dados" and "pdf_bytes" not in r


def test_competencia_sem_tabela_explica_e_nao_estima():
    r = AgenteContabil().processar_pedido({"salario": 3000, "competencia": "2035-01-01"})
    assert r["success"] is False and r["codigo"] == "competencia_sem_tabela"


def test_falha_na_auditoria_nao_derruba_o_pedido():
    def quebrada(*_):
        raise RuntimeError("disco cheio")

    r = AgenteContabil(auditoria=quebrada, hoje=HOJE).processar_pedido({"salario": 3000})
    assert r["success"]
