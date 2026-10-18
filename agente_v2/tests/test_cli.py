"""Comandos de administração que não dependem de rede."""

from agente_v2 import cli


def test_carregar_env_le_chave_valor_com_aspas_e_comentarios(tmp_path):
    arq = tmp_path / ".env.teste"
    arq.write_text('# comentário\nGROQ_API_KEY="abc"\n\nDEEPSEEK_API_KEY = def \nsem_igual\nGEMINI_MODEL=m=1\n', encoding="utf-8")
    assert cli.carregar_env(str(arq)) == {"GROQ_API_KEY": "abc", "DEEPSEEK_API_KEY": "def", "GEMINI_MODEL": "m=1"}


def test_verificar_ia_sem_nenhuma_chave_avisa_e_sai_com_2(tmp_path, monkeypatch, capsys):
    for nome in ("GROQ_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(nome, raising=False)
    vazio = tmp_path / "vazio.env"
    vazio.write_text("", encoding="utf-8")
    assert cli.main(["verificar-ia", "--env-file", str(vazio)]) == 2
    assert "Nenhuma chave de IA" in capsys.readouterr().err


def test_verificar_ia_avisa_quais_chaves_estao_em_branco_no_arquivo(tmp_path, monkeypatch, capsys):
    for nome in ("GROQ_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(nome, raising=False)
    arq = tmp_path / ".env.teste"
    arq.write_text("GROQ_API_KEY=\nDEEPSEEK_API_KEY=\n", encoding="utf-8")
    assert cli.main(["verificar-ia", "--env-file", str(arq)]) == 2
    err = capsys.readouterr().err
    assert "estão em branco: GROQ_API_KEY, DEEPSEEK_API_KEY" in err and "GEMINI" not in err.split("em branco:")[1]


# ---------------------------------------------------------------- baixar-extrato (navegador de verdade contra portais falsos)
import json  # noqa: E402

from contabil_agente.tests.portal_fgts_falso import PortalFalso  # noqa: E402
from contabil_agente.tests.portal_pgmei_falso import PgmeiFalso  # noqa: E402
from contabil_agente.tests.test_rpa_fgts import canal  # noqa: E402,F401 - fixture que escolhe o navegador disponível


def _rodar(args, capsys):
    codigo = cli.main(["baixar-extrato", *args, "--headless"])
    return codigo, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_baixar_extrato_fgts_pela_cli(canal, tmp_path, capsys):
    p = PortalFalso(com_captcha=False)
    try:
        codigo, saida = _rodar(["--portal", "fgts", "--documento", "529.982.247-25", "--url", p.url, "--saida", str(tmp_path), *(["--canal", canal] if canal else [])], capsys)
    finally:
        p.parar()
    assert codigo == 0 and saida["status"] == "ok" and len(saida["sha256"]) == 64 and open(saida["caminho"], "rb").read().startswith(b"%PDF-")


def test_baixar_extrato_pgmei_pela_cli_com_ano(canal, tmp_path, capsys, monkeypatch):
    p = PgmeiFalso()
    # sem pessoa para resolver o hCaptcha nesta execução sem janela, o token vem preenchido de antemão pelo portal falso
    p.pre_resolvido = True
    try:
        codigo, saida = _rodar(["--portal", "pgmei", "--documento", "11.222.333/0001-81", "--ano", "2025", "--url", p.url, "--saida", str(tmp_path), *(["--canal", canal] if canal else [])], capsys)
    finally:
        p.parar()
    assert codigo == 0 and saida["status"] == "ok" and p.anos_pedidos == ["2025"]


def test_baixar_extrato_portal_que_bloqueia_sai_com_codigo_3_e_mensagem_clara(canal, tmp_path, capsys):
    p = PortalFalso(com_captcha=False, variante="bloqueado")
    try:
        codigo, saida = _rodar(["--portal", "fgts", "--documento", "529.982.247-25", "--url", p.url, "--saida", str(tmp_path), *(["--canal", canal] if canal else [])], capsys)
    finally:
        p.parar()
    assert codigo == 3 and saida["status"] == "bloqueado" and "navegador normal" in saida["mensagem"]


def test_baixar_extrato_documento_invalido_sai_com_erro_e_nao_abre_navegador(tmp_path, capsys):
    codigo, saida = _rodar(["--portal", "pgmei", "--documento", "123", "--saida", str(tmp_path)], capsys)
    assert codigo == 1 and saida["motivo"] == "cnpj_invalido"
