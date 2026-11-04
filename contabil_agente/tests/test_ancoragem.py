"""Âncora externa da trilha: pega o que a cadeia HMAC sozinha não pega (cadeia refeita com a chave e backup antigo restaurado)."""

import json
import shutil

import httpx
import pytest

from contabil_agente.security.ancoragem import AncoraEmDiretorio, AncoraHTTP, Ancorador, ErroDeAncora, ancoragem_do_ambiente
from contabil_agente.security.worm_audit import AuditoriaError, WormAudit

CHAVE = "k" * 40


def trilha(tmp_path, eventos=("login", "calculo", "logout")):
    worm = WormAudit(tmp_path / "audit", CHAVE, fsync=False)
    for e in eventos:
        worm.append(e, {"n": e}, tenant="empresa_a")
    return worm


def test_ancora_publicada_bate_com_a_trilha_mesmo_depois_que_ela_cresce(tmp_path):
    worm = trilha(tmp_path)
    anc = Ancorador(worm, [AncoraEmDiretorio(tmp_path / "fora")])
    publicado = anc.ancorar("empresa_a")
    assert publicado["ancora"]["seq"] == 3 and publicado["recibos"][0]["destino"] == "diretorio" and publicado["erros"] == []
    worm.append("mais", {}, tenant="empresa_a")
    [c] = anc.conferir("empresa_a")
    assert c.ok and c.conferidas == 1 and c.ultima_seq == 3


def test_cadeia_refeita_com_a_chave_passa_na_verificacao_mas_a_ancora_acusa(tmp_path):
    worm = trilha(tmp_path)
    Ancorador(worm, [AncoraEmDiretorio(tmp_path / "fora")]).ancorar("empresa_a")
    # quem tem o disco E a chave apaga a trilha e escreve outra, com a cadeia HMAC perfeita
    shutil.rmtree(tmp_path / "audit")
    refeita = WormAudit(tmp_path / "audit", CHAVE, fsync=False)
    for e in ("login", "calculo_alterado", "logout"):
        refeita.append(e, {"n": e}, tenant="empresa_a")
    assert refeita.verificar("empresa_a").ok  # a cadeia sozinha não vê nada de errado
    [c] = Ancorador(refeita, [AncoraEmDiretorio(tmp_path / "fora")]).conferir("empresa_a")
    assert not c.ok and "reescrita" in c.problemas[0]


def test_backup_antigo_restaurado_volta_no_tempo_e_a_ancora_acusa(tmp_path):
    worm = trilha(tmp_path, ("login",))
    shutil.copytree(tmp_path / "audit", tmp_path / "backup")  # arquivo e .head juntos, de quando havia 1 entrada
    for e in ("calculo", "logout"):
        worm.append(e, {}, tenant="empresa_a")
    anc = Ancorador(worm, [AncoraEmDiretorio(tmp_path / "fora")])
    anc.ancorar("empresa_a")  # âncora na sequência 3
    shutil.rmtree(tmp_path / "audit")
    shutil.copytree(tmp_path / "backup", tmp_path / "audit")
    assert worm.verificar("empresa_a").ok  # arquivo e .head restaurados juntos: a cadeia confere
    [c] = anc.conferir("empresa_a")
    assert not c.ok and "não existe mais" in c.problemas[0]


def test_trilha_adulterada_nao_ganha_ancora(tmp_path):
    worm = trilha(tmp_path)
    arq = worm._caminho("empresa_a")
    arq.write_text(arq.read_text(encoding="utf-8").replace('"n":"calculo"', '"n":"outro"'), encoding="utf-8")
    with pytest.raises(AuditoriaError):
        Ancorador(worm, [AncoraEmDiretorio(tmp_path / "fora")]).ancorar("empresa_a")
    assert not (tmp_path / "fora" / "empresa_a.ancoras.jsonl").exists()


class ServicoDeAncoras:
    """Um serviço de âncoras de mentira do outro lado do HTTPS: guarda no POST, devolve no GET."""

    def __init__(self):
        self.guardadas, self.cabecalhos = [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.cabecalhos.append(request.headers.get("authorization"))
        if request.method == "POST":
            self.guardadas.append(json.loads(request.content))
            return httpx.Response(201, json={"ok": True})
        tenant = request.url.params.get("tenant")
        return httpx.Response(200, json={"ancoras": [a for a in self.guardadas if a["tenant"] == tenant]})


def test_ancora_num_servico_https_com_token(tmp_path):
    servico = ServicoDeAncoras()
    destino = AncoraHTTP("https://ancoras.exemplo/api", token="t0k3n-de-teste", transport=httpx.MockTransport(servico))
    anc = Ancorador(trilha(tmp_path), [destino])
    anc.ancorar("empresa_a")
    assert servico.guardadas[0]["seq"] == 3 and len(servico.guardadas[0]["hash"]) == 64
    [c] = anc.conferir("empresa_a")
    assert c.ok and c.conferidas == 1 and servico.cabecalhos == ["Bearer t0k3n-de-teste"] * 2


def test_https_obrigatorio_e_servico_fora_do_ar_vira_erro_claro(tmp_path):
    with pytest.raises(ValueError):
        AncoraHTTP("http://ancoras.exemplo/api")
    AncoraHTTP("http://127.0.0.1:9000/ancoras")  # http só para um serviço local
    fora = AncoraHTTP("https://ancoras.exemplo/api", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    worm = trilha(tmp_path)
    with pytest.raises(ErroDeAncora):
        Ancorador(worm, [fora]).ancorar("empresa_a")
    [c] = Ancorador(worm, [fora]).conferir("empresa_a")
    assert not c.ok and "Não consegui ler" in c.problemas[0]


def test_um_destino_fora_do_ar_nao_impede_o_outro(tmp_path):
    fora = AncoraHTTP("https://ancoras.exemplo/api", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    r = Ancorador(trilha(tmp_path), [fora, AncoraEmDiretorio(tmp_path / "fora")]).ancorar("empresa_a")
    assert [x["destino"] for x in r["recibos"]] == ["diretorio"] and r["erros"] and r["erros"][0].startswith("http:")


def test_configuracao_pelo_ambiente(tmp_path):
    worm = trilha(tmp_path)
    assert ancoragem_do_ambiente(worm, {}) is None
    anc = ancoragem_do_ambiente(worm, {"AUDIT_ANCHOR_DIR": str(tmp_path / "fora"), "AUDIT_ANCHOR_URL": "https://ancoras.exemplo/api"})
    assert [d.nome for d in anc.destinos] == ["diretorio", "http"]
    with pytest.raises(ValueError):
        ancoragem_do_ambiente(worm, {"AUDIT_ANCHOR_DIR": str(tmp_path / "audit" / "ancoras")})  # dentro da própria trilha
