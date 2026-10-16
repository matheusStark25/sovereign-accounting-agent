"""Isola os testes da API: nenhum teste grava na pasta de dados real."""

import pytest


@pytest.fixture(autouse=True)
def dados_isolados(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "dados"))
    monkeypatch.setenv("AGENTE_ENV", "dev")
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_URL", raising=False)
