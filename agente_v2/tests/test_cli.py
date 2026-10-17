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
