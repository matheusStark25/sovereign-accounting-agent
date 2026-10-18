"""Testes AO VIVO dos provedores de IA: falam com Groq, DeepSeek e Gemini de verdade.

Só rodam quando a chave existe (no ambiente ou no arquivo ``.env.teste``, que o git ignora); sem chave são
pulados, então o CI não depende de segredo. Confirmam o que os testes com resposta simulada não conseguem:
que a chave vale, que o modelo configurado ainda existe no provedor, que o formato da requisição é aceito e que
a resposta real passa pelo nosso código (pipeline de documentos e chat).

    python -m pytest contabil_agente/tests/test_ia_ao_vivo.py -v
"""

import os
from pathlib import Path

import pytest

from agente_v2.cli import carregar_env
from contabil_agente.chat.engine import ChatEngine
from contabil_agente.chat.llm import GroqLLM
from contabil_agente.pipeline import ArquivoDestino, DocumentDispatcher, DeepSeek, Gemini, Groq, HistoricoDocumentos
from contabil_agente.pipeline.provedores import MODELO_GROQ
from contabil_agente.security.worm_audit import WormAudit

from . import amostras_documentos as am

ARQUIVO_ENV = Path(__file__).resolve().parents[2] / ".env.teste"
ENV = {**(carregar_env(str(ARQUIVO_ENV)) if ARQUIVO_ENV.is_file() else {}), **{k: v for k, v in os.environ.items() if k.endswith("_API_KEY") or k.endswith("_MODEL")}}


def _chave(nome: str):
    return pytest.mark.skipif(not ENV.get(nome), reason=f"{nome} não configurada (ponha em .env.teste para testar ao vivo)")


def _deepseek():
    return DeepSeek(ENV["DEEPSEEK_API_KEY"], ENV.get("DEEPSEEK_MODEL") or DeepSeek.__init__.__defaults__[0])


def _gemini():
    return Gemini(ENV["GEMINI_API_KEY"], ENV.get("GEMINI_MODEL") or Gemini.__init__.__defaults__[0])


def _groq():
    from contabil_agente.chat.llm import MODELO_PADRAO

    return GroqLLM(ENV["GROQ_API_KEY"], ENV.get("GROQ_MODEL") or MODELO_PADRAO)


def _confere(v):
    assert v["chave_valida"], v
    assert v["modelo_existe"], v  # se falhar, "alternativas" mostra o que o provedor lista hoje
    assert v["chamada_ok"], v


@_chave("DEEPSEEK_API_KEY")
def test_deepseek_chave_modelo_e_chamada_reais():
    _confere(_deepseek().verificar())


@_chave("GEMINI_API_KEY")
def test_gemini_chave_modelo_e_chamada_reais():
    _confere(_gemini().verificar())


@_chave("GROQ_API_KEY")
def test_groq_chave_modelo_e_chamada_reais():
    _confere(_groq().verificar())


@_chave("GROQ_API_KEY")
def test_chat_responde_pergunta_geral_com_o_llm_real():
    resp = ChatEngine(llm=_groq()).responder({}, "Explique em uma frase o que é o FGTS.")
    assert resp["origem"] == "llm", resp
    assert len(resp["resposta"]) > 20


def _dispatcher(tmp_path, worker, revisor):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    return DocumentDispatcher(audit, HistoricoDocumentos(tmp_path / "h.db"), worker_llm=worker, revisor_llm=revisor, destinos=[ArquivoDestino(tmp_path / "arq")])


@pytest.mark.skipif(not (ENV.get("DEEPSEEK_API_KEY") or ENV.get("GEMINI_API_KEY")), reason="nenhuma chave de DeepSeek/Gemini configurada")
def test_pipeline_de_documentos_com_os_llms_reais(tmp_path):
    worker = _deepseek() if ENV.get("DEEPSEEK_API_KEY") else None
    revisor = _gemini() if ENV.get("GEMINI_API_KEY") else None
    r = _dispatcher(tmp_path, worker, revisor).process(conteudo=am.HOLERITE.encode("utf-8"), tenant="t1", usar_ia=True)
    assert r.estado == "ARCHIVED" and r.tipo == "HOLERITE", r.to_dict()
    assert r.extracted_data["liquido"] == "4973.39"  # o valor vem do texto, nunca do LLM
    if worker:
        assert r.agentes["worker"] == "llm", r.agentes  # o DeepSeek respondeu e a resposta passou no nosso parser
    if revisor:
        assert r.agentes["revisor"] == "llm", r.agentes


def _groq_http():
    return Groq(ENV["GROQ_API_KEY"], ENV.get("GROQ_MODEL") or MODELO_GROQ)


@_chave("GROQ_API_KEY")
def test_groq_como_provedor_do_pipeline_chave_modelo_e_chamada_reais():
    _confere(_groq_http().verificar())


@_chave("GROQ_API_KEY")
def test_pipeline_de_documentos_com_a_groq_como_worker_e_revisor(tmp_path):
    g = _groq_http()
    r = _dispatcher(tmp_path, g, g).process(conteudo=am.HOLERITE.encode("utf-8"), tenant="t1", usar_ia=True)
    assert r.estado == "ARCHIVED" and r.tipo == "HOLERITE", r.to_dict()
    assert r.extracted_data["liquido"] == "4973.39"  # o valor vem do texto, nunca do LLM
    assert r.agentes["worker"] == "llm" and r.agentes["revisor"] == "llm", r.agentes  # as duas respostas reais passaram no nosso parser
