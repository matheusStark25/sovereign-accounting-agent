"""Âncora externa da auditoria pela API e pela linha de comando."""

from contabil_agente.security.ancoragem import AncoraEmDiretorio, Ancorador
from contabil_agente.security.worm_audit import WormAudit

from .test_api import client, entrar, llm  # noqa: F401


def test_publicar_e_conferir_a_ancora_pela_api(client, tmp_path):  # noqa: F811
    adm = entrar(client, "admin")
    assert client.post("/api/v1/auditoria/ancorar", headers=adm).status_code == 409  # nenhum destino configurado
    assert client.get("/api/v1/auditoria/verificar", headers=adm).json()["ancoragem"] == {"configurada": False}
    client.app.state.ancorador = Ancorador(client.app.state.audit.worm, [AncoraEmDiretorio(tmp_path / "fora")])
    r = client.post("/api/v1/auditoria/ancorar", headers=adm)
    assert r.status_code == 200 and r.json()["recibos"][0]["destino"] == "diretorio"
    v = client.get("/api/v1/auditoria/verificar", headers=adm).json()
    assert v["ok"] is True and v["ancoragem"]["ok"] is True and v["ancoragem"]["destinos"][0]["conferidas"] == 1
    assert "audit_anchored" in [e["evento"] for e in client.app.state.audit.worm.ler("empresa_a")]


def test_ancorar_exige_o_perfil_de_auditoria(client, tmp_path):  # noqa: F811
    client.app.state.ancorador = Ancorador(client.app.state.audit.worm, [AncoraEmDiretorio(tmp_path / "fora")])
    assert client.post("/api/v1/auditoria/ancorar", headers=entrar(client, "maria")).status_code == 403


def test_verificacao_pela_api_acusa_a_trilha_refeita_com_a_chave(client, tmp_path):  # noqa: F811
    adm = entrar(client, "admin")
    worm = client.app.state.audit.worm
    client.app.state.ancorador = Ancorador(worm, [AncoraEmDiretorio(tmp_path / "fora")])
    assert client.post("/api/v1/auditoria/ancorar", headers=adm).status_code == 200
    worm._caminho("empresa_a").unlink()  # quem tem o disco e a chave refaz a trilha do zero
    worm._head_path("empresa_a").unlink()
    for _ in range(5):
        worm.append("login", {}, tenant="empresa_a")
    assert worm.verificar("empresa_a").ok  # a cadeia nova é perfeita
    v = client.get("/api/v1/auditoria/verificar", headers=adm).json()
    assert v["ok"] is False and any("reescrita" in p for p in v["problemas"])


def test_cli_ancora_e_confere(tmp_path, monkeypatch, capsys):
    from agente_v2 import cli

    monkeypatch.setenv("AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("AUDIT_HMAC_KEY", "k" * 40)
    monkeypatch.delenv("AUDIT_ANCHOR_URL", raising=False)
    monkeypatch.delenv("AUDIT_ANCHOR_DIR", raising=False)
    assert cli.main(["ancorar-auditoria"]) == 2  # sem destino configurado
    monkeypatch.setenv("AUDIT_ANCHOR_DIR", str(tmp_path / "fora"))
    WormAudit(tmp_path / "audit", "k" * 40, fsync=False).append("x", {}, tenant="t1")
    assert cli.main(["ancorar-auditoria"]) == 0
    assert cli.main(["conferir-ancoras", "--tenant", "t1"]) == 0
    assert '"conferidas": 1' in capsys.readouterr().out
