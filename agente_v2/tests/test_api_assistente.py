"""A Maria Helena pela API: as ferramentas enxergam só os documentos da empresa de quem pergunta, e a resposta diz quais
ferramentas ela usou."""

import json

from contabil_agente.chat import ChatEngine
from contabil_agente.tests.test_assistente import LLMRoteirizado

from .test_api import client, entrar, llm  # noqa: F401
from .test_api_documentos import HOLERITE, enviar


def test_ela_consulta_os_documentos_da_empresa_e_diz_que_ferramenta_usou(client):  # noqa: F811
    h = entrar(client, "maria")
    assert enviar(client, h).status_code == 200  # um holerite da empresa_a entra pelo pipeline
    roteiro = LLMRoteirizado([("documentos_recentes", {"limite": 5})],
                             lambda rs: f"Você enviou {rs[0]['total']} documento(s); o último é {rs[0]['documentos'][0]['tipo']}.")
    client.app.state.chat_engine = ChatEngine(llm=roteiro)
    r = client.post("/api/chat", json={"message": "o que tem no último documento que eu mandei?"}, headers=h)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["response"] == "Você enviou 1 documento(s); o último é HOLERITE."
    assert corpo["ferramentas"] == [{"ferramenta": "documentos_recentes", "status": "ok"}]
    assert "11222333000181" not in json.dumps(roteiro.resultados)  # o CNPJ do holerite volta mascarado ao LLM


def test_outra_empresa_nao_ve_os_documentos(client):  # noqa: F811
    assert enviar(client, entrar(client, "maria")).status_code == 200
    client.app.state.lgpd.registrar_consentimento("empresa_b", None, "envio_a_provedor_de_ia", True, "setup")
    roteiro = LLMRoteirizado([("documentos_recentes", {})], lambda rs: f"{rs[0]['total']} documento(s).")
    client.app.state.chat_engine = ChatEngine(llm=roteiro)
    r = client.post("/api/chat", json={"message": "quais documentos eu mandei?"}, headers=entrar(client, "joao"))
    assert r.json()["response"] == "0 documento(s)."


def test_calculo_pela_ferramenta_libera_o_pdf_da_conversa(client):  # noqa: F811
    h = entrar(client, "maria")
    roteiro = LLMRoteirizado([("calcular", {"tipo": "das_mei", "dados": {"atividade_mei": "servicos", "competencia": "09/2026"}})],
                             lambda rs: "Calculei o DAS.")
    client.app.state.chat_engine = ChatEngine(llm=roteiro)
    r = client.post("/api/chat", json={"message": "me ajuda com a guia mensal do meu MEI de serviços"}, headers=h).json()
    assert r["tipo"] == "das_mei" and r["dados_calculados"]
    pdf = client.get(f"/api/chat/{r['session_id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")


def test_quem_responde_e_a_maria_helena_e_cada_empresa_tem_as_suas_ferramentas(client):  # noqa: F811
    assert ChatEngine().persona == "MARIA_HELENA"  # o nome da tela e o prompt do modelo agora são a mesma pessoa
    a, b = client.app.state.ferramentas_da_assistente("empresa_a"), client.app.state.ferramentas_da_assistente("empresa_b")
    assert a.tenant == "empresa_a" and b.tenant == "empresa_b" and a is not b
