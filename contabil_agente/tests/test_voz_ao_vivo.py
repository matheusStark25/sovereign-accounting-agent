"""Whisper AO VIVO com uma fala real em português (gerada com a voz pt-BR do Windows e guardada em ``tests/dados``).

Roda quando há ``GROQ_API_KEY`` (ambiente ou ``.env.teste``); sem chave é pulado. Confere o que o STT simulado não confere: que o
modelo ainda existe, que o formato do pedido é aceito e que a fala vira o texto certo.
"""

from pathlib import Path

import pytest

from contabil_agente.voz import WhisperGroq

from .test_ia_ao_vivo import ENV

DADOS = Path(__file__).resolve().parent / "dados"
pytestmark = pytest.mark.skipif(not ENV.get("GROQ_API_KEY"), reason="GROQ_API_KEY não configurada (ponha em .env.teste para testar ao vivo)")


def _whisper():
    return WhisperGroq(ENV["GROQ_API_KEY"], ENV.get("GROQ_STT_MODEL") or "whisper-large-v3-turbo")


def test_chave_modelo_e_chamada_do_whisper_sao_reais():
    v = _whisper().verificar()
    assert v["chave_valida"] and v["modelo_existe"] and v["chamada_ok"], v


def test_fala_em_portugues_vira_o_texto_certo():
    texto = _whisper().transcrever((DADOS / "fala_calcular_rescisao.wav").read_bytes(), "fala.wav")
    assert "calcular" in texto.lower() and "rescis" in texto.lower(), texto


def test_fala_formal_mais_longa_mantem_o_sentido():
    texto = _whisper().transcrever((DADOS / "fala_formal_ferias.wav").read_bytes(), "fala.wav").lower()
    assert "gostaria de calcular" in texto and "f" in texto and "funcion" in texto, texto
