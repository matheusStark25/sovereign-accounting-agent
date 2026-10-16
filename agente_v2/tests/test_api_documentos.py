"""Upload de documentos e verificação da trilha de auditoria pela API."""

import pytest

from .test_api import client, entrar, llm  # noqa: F401  (fixtures compartilhadas)

HOLERITE = (
    "HOLERITE - Competência: 09/2026\nSalário base 6.000,00\nTotal de proventos 6.000,00\nINSS 641,51\n"
    "IRRF 385,10\nTotal de descontos 1.026,61\nFGTS 480,00\nLíquido a receber 4.973,39\nCNPJ 11.222.333/0001-81\n"
)


def enviar(client, headers, conteudo=HOLERITE.encode(), nome="holerite.txt", **campos):
    return client.post("/api/v1/documentos", files={"arquivo": (nome, conteudo)}, data=campos, headers=headers)


def test_upload_processa_o_documento_pelo_pipeline(client):
    r = enviar(client, entrar(client))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tipo"] == "HOLERITE" and j["estado"] == "ARCHIVED" and j["extracted_data"]["liquido"] == "4973.39"
    assert j["calculations"]["inss_recalculado"] == "641.51" and j["audit_trail_id"].startswith("empresa_a:")


def test_upload_exige_login_e_permissao(client):
    assert client.post("/api/v1/documentos", files={"arquivo": ("a.txt", b"x")}).status_code == 401
    assert enviar(client, entrar(client, "vera")).status_code == 403


def test_upload_de_tipo_nao_identificado_e_arquivo_invalido_dao_422(client):
    h = entrar(client)
    r = enviar(client, h, b"papo furado sem nada", "x.txt")
    assert r.status_code == 422 and r.json()["estado"] == "CLASSIFYING" and r.json()["falha"]
    assert enviar(client, h, b"   ", "vazio.txt").status_code == 422
    assert enviar(client, h, b"nao e pdf", "falso.pdf").status_code == 422


def test_upload_com_tipo_informado_e_persona(client):
    r = enviar(client, entrar(client), tipo="holerite", persona="MARIA_HELENA")
    assert r.status_code == 200 and r.json()["tipo"] == "HOLERITE"
    ruim = enviar(client, entrar(client), tipo="ASTROLOGIA")
    assert ruim.status_code == 422 and "desconhecido" in ruim.json()["falha"]


def test_upload_grande_demais_e_recusado(client, monkeypatch):
    import agente_v2.main as m

    monkeypatch.setattr(m, "TAMANHO_MAXIMO", 100)
    assert enviar(client, entrar(client), b"x" * 101, "g.txt").status_code == 413


def test_o_arquivo_de_cada_tenant_fica_separado(client, tmp_path):
    enviar(client, entrar(client, "maria"))
    enviar(client, entrar(client, "joao"))
    assert (tmp_path / "arquivo" / "empresa_a" / "HOLERITE").exists()
    assert (tmp_path / "arquivo" / "empresa_b" / "HOLERITE").exists()


def test_documento_duplicado_e_avisado_pelo_historico_do_tenant(client):
    h = entrar(client)
    enviar(client, h)
    r = enviar(client, h).json()
    assert "documento_duplicado" in [a["codigo"] for a in r["alertas"]]


def test_lista_de_tipos(client):
    r = client.get("/api/v1/documentos/tipos", headers=entrar(client))
    assert r.status_code == 200 and len(r.json()["tipos"]) >= 23


def test_verificacao_da_trilha_so_para_quem_pode_ver_logs(client):
    h = entrar(client)
    enviar(client, h)
    assert client.get("/api/v1/auditoria/verificar", headers=h).status_code == 403
    r = client.get("/api/v1/auditoria/verificar", headers=entrar(client, "admin"))
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["entradas"] >= 1
    assert len(r.json()["ancora"]["hash"]) == 64


def test_verificacao_acusa_trilha_adulterada(client):
    h = entrar(client)
    enviar(client, h)
    adm = entrar(client, "admin")
    arq = client.app.state.audit.worm._caminho("empresa_a")
    linhas = arq.read_text(encoding="utf-8").splitlines()
    assert '"evento":"login"' in linhas[0]
    linhas[0] = linhas[0].replace('"evento":"login"', '"evento":"logout"')
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    r = client.get("/api/v1/auditoria/verificar", headers=adm)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["problemas"]
