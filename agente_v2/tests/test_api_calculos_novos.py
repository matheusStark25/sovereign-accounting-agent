"""Pró-labore, GPS, DAS do MEI e DARF pela API REST: valores, pergunta do que falta, PDF e auditoria."""

import pytest

from .test_api import client, entrar, llm  # noqa: F401


def _post(client, tipo, corpo):
    return client.post(f"/api/v1/calculo/{tipo}", json={"competencia": "2026-10-01", **corpo}, headers=entrar(client))


def test_lista_os_novos_tipos(client):
    tipos = client.get("/api/v1/calculo/tipos", headers=entrar(client)).json()["tipos"]
    for tipo in ("prolabore", "gps", "das_mei", "darf"):
        assert tipo in tipos


def test_prolabore_pela_api(client):
    r = _post(client, "prolabore", {"prolabore": 5000, "regime": "presumido"})
    assert r.status_code == 200
    res = r.json()["resultado"]
    assert res["inss_socio"] == 550.0 and res["inss_patronal"] == 1000.0 and res["custo_total_empresa"] == 6000.0


def test_gps_e_das_mei_pela_api(client):
    assert _post(client, "gps", {"tipo_gps": "contribuinte_individual", "base": 4000}).json()["resultado"]["valor"] == 800.0
    assert _post(client, "das_mei", {"atividade_mei": "servicos"}).json()["resultado"]["valor"] == 86.05


def test_darf_pede_a_selic_com_422_e_depois_calcula(client):
    corpo = {"valor_principal": 1000, "vencimento": "20/08/2026", "pagamento": "15/10/2026"}
    r = _post(client, "darf", corpo)
    assert r.status_code == 422 and r.json()["faltando"] == ["selic_acumulada"]
    ok = _post(client, "darf", {**corpo, "selic_acumulada": 0.9})
    assert ok.status_code == 200 and ok.json()["resultado"]["total"] == 1203.8


@pytest.mark.parametrize("tipo,corpo", [
    ("prolabore", {"prolabore": 5000}),
    ("gps", {"tipo_gps": "baixa_renda"}),
    ("das_mei", {"atividade_mei": "comercio"}),
    ("darf", {"valor_principal": 1000, "vencimento": "28/08/2026", "pagamento": "10/09/2026"}),
])
def test_pdf_dos_novos_tipos_e_auditado(client, tipo, corpo):
    r = client.post(f"/api/v1/calculo/{tipo}/pdf", json={"dados": {"competencia": "2026-10-01", **corpo}}, headers=entrar(client))
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-") and len(r.headers["x-calculo-sha256"]) == 64


def test_sem_tabela_da_competencia_a_api_recusa_em_vez_de_estimar(client):
    r = _post(client, "das_mei", {"atividade_mei": "servicos", "competencia": "2010-01-01"})
    assert r.status_code == 422 and r.json()["codigo"] == "competencia_sem_tabela"


def test_competencia_por_mes_e_ano_e_a_metrica_que_o_prometheus_le(client):  # noqa: F811
    # o mesmo pedido do job de observabilidade do CI: competência "2026-09" (antes só DD/MM/AAAA passava e a API devolvia 422)
    h = entrar(client)
    for competencia in ("2026-09", "09/2026", "01/09/2026"):
        r = client.post("/api/v1/calculo/inss", json={"salario": 3000, "competencia": competencia}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["resultado"]["competencia"] == "2026-09"
    assert client.post("/api/v1/calculo/inss", json={"salario": 3000, "competencia": "2026-13"}, headers=h).status_code == 422
    metricas = client.get("/metrics").text
    assert 'agente_calculos_total{resultado="ok",tipo="inss"}' in metricas
