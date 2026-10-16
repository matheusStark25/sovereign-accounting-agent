"""A trilha WORM precisa denunciar qualquer apagamento, troca ou reordenação."""

import json
import threading

import pytest

from contabil_agente.security.worm_audit import AuditoriaError, WormAudit

CHAVE = "k" * 40


@pytest.fixture()
def audit(tmp_path):
    return WormAudit(tmp_path / "audit", CHAVE)


def preencher(audit, n=5, tenant="t1"):
    return [audit.append("evento", {"i": i}, tenant=tenant, ator="u") for i in range(n)]


def linhas(audit, tenant="t1"):
    return audit._caminho(tenant).read_text(encoding="utf-8").splitlines()


def reescrever(audit, novas, tenant="t1"):
    audit._caminho(tenant).write_text("\n".join(novas) + "\n", encoding="utf-8")


def test_cadeia_integra_verifica_ok(audit):
    recibos = preencher(audit)
    v = audit.verificar("t1")
    assert v.ok and v.entradas == 5 and v.head_seq == 5
    assert [r.seq for r in recibos] == [1, 2, 3, 4, 5]
    assert recibos[0].id.startswith("t1:1:")


def test_chave_curta_e_recusada(tmp_path):
    with pytest.raises(ValueError):
        WormAudit(tmp_path, "curta")


def test_sem_chave_em_producao_nao_sobe(tmp_path):
    with pytest.raises(ValueError):
        WormAudit.do_ambiente(tmp_path, env={})


def test_dev_gera_chave_persistente_e_a_mesma_verifica_depois(tmp_path):
    a = WormAudit.do_ambiente(tmp_path, env={"AGENTE_ENV": "dev"})
    a.append("x", {}, tenant="t")
    b = WormAudit.do_ambiente(tmp_path, env={"AGENTE_ENV": "dev"})
    assert b.verificar("t").ok


def test_alterar_um_campo_e_detectado(audit):
    preencher(audit)
    ls = linhas(audit)
    e = json.loads(ls[2])
    e["dados"]["i"] = 999
    ls[2] = json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    reescrever(audit, ls)
    v = audit.verificar("t1")
    assert not v.ok and any("adulterado" in p for p in v.problemas)


def test_apagar_uma_linha_do_meio_e_detectado(audit):
    preencher(audit)
    ls = linhas(audit)
    del ls[2]
    reescrever(audit, ls)
    v = audit.verificar("t1")
    assert not v.ok and any("sequência" in p or "encadeia" in p for p in v.problemas)


def test_reordenar_e_detectado(audit):
    preencher(audit)
    ls = linhas(audit)
    ls[1], ls[2] = ls[2], ls[1]
    reescrever(audit, ls)
    assert not audit.verificar("t1").ok


def test_cortar_o_final_e_detectado_pelo_head(audit):
    preencher(audit)
    reescrever(audit, linhas(audit)[:3])  # cadeia continua válida até a 3, mas o head diz 5
    v = audit.verificar("t1")
    assert not v.ok and any(".head" in p for p in v.problemas)


def test_apagar_o_arquivo_e_detectado(audit):
    preencher(audit)
    audit._caminho("t1").unlink()
    assert not audit.verificar("t1").ok


def test_forjar_entrada_sem_a_chave_e_detectado(audit):
    preencher(audit, 2)
    outra = WormAudit(audit.dir, "z" * 40)
    ls = linhas(audit)
    ultima = json.loads(ls[-1])
    corpo = {"seq": 3, "ts": "2026-01-01T00:00:00Z", "tenant": "t1", "ator": "x", "evento": "forjado", "dados": {}, "prev": ultima["hash"]}
    forjada = {**corpo, "hash": outra._mac(corpo["prev"], corpo)}
    audit._caminho("t1").write_text("\n".join(ls + [json.dumps(forjada)]) + "\n", encoding="utf-8")
    assert not audit.verificar("t1").ok


def test_cpf_e_email_sao_mascarados_antes_de_gravar(audit):
    audit.append("upload", {"obs": "CPF 529.982.247-25 e joao@empresa.com"}, tenant="t1")
    texto = audit._caminho("t1").read_text(encoding="utf-8")
    assert "529.982.247-25" not in texto and "joao@empresa.com" not in texto and "***CPF***" in texto
    assert audit.verificar("t1").ok


def test_tenant_malicioso_e_recusado(audit):
    for ruim in ("../fora", "a/b", "", "..", "x" * 65, "a b"):
        with pytest.raises(ValueError):
            audit.append("x", {}, tenant=ruim)


def test_tenants_isolados(audit):
    preencher(audit, 2, "a")
    preencher(audit, 3, "b")
    assert audit.verificar("a").entradas == 2 and audit.verificar("b").entradas == 3
    assert audit.tenants() == ["a", "b"]


def test_escrita_concorrente_mantem_a_cadeia(audit):
    def escreve(k):
        for i in range(10):
            audit.append("c", {"k": k, "i": i}, tenant="conc")

    ts = [threading.Thread(target=escreve, args=(k,)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    v = audit.verificar("conc")
    assert v.ok and v.entradas == 40


def test_ler_pagina_e_ancora(audit):
    preencher(audit, 6)
    assert [e["seq"] for e in audit.ler("t1", inicio=4)] == [4, 5, 6]
    a = audit.ancora("t1")
    assert a["seq"] == 6 and len(a["hash"]) == 64


def test_falha_de_disco_nao_e_engolida(audit, monkeypatch):
    import contabil_agente.security.worm_audit as w

    monkeypatch.setattr(w.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disco cheio")))
    with pytest.raises(AuditoriaError):
        audit.append("x", {}, tenant="t1")
