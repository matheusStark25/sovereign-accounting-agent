"""Canal de voz (WebSocket): autenticação, consentimento, áudio em pedaços, resposta frase por frase, auditoria e limites.

O STT daqui é um falso que só devolve o texto combinado (a transcrição real, com o Whisper, está em
``contabil_agente/tests/test_voz_ao_vivo.py``). Todo o resto é o servidor de verdade.
"""

import json
from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from contabil_agente.core.prompts import obter_prompt
from contabil_agente.security.audit_trail_manager import AuditoriaError

from .test_api import client, entrar, llm  # noqa: F401


class STTFalso:
    def __init__(self, texto="calcular INSS"):
        self.texto, self.recebidos = texto, []

    def transcrever(self, audio, nome="fala.webm", idioma="pt"):
        self.recebidos.append((audio, nome, idioma))
        return self.texto


def token(client, usuario="maria"):
    return entrar(client, usuario)["Authorization"].split()[1]


@contextmanager
def voz(client, usuario="maria", stt=None):
    client.app.state.stt = stt
    with client.websocket_connect("/ws/voz") as ws:
        ws.send_json({"tipo": "autenticar", "token": token(client, usuario)})
        pronto = ws.receive_json()
        assert pronto["tipo"] == "pronto", pronto
        ws.pronto = pronto
        yield ws


def falar(ws, pedacos=(b"abc", b"def", b"ghi"), formato="webm"):
    ws.send_json({"tipo": "inicio", "formato": formato})
    for p in pedacos:
        ws.send_bytes(p)
    ws.send_json({"tipo": "fim"})


def receber_ate_o_fim(ws):
    quadros = []
    while True:
        q = ws.receive_json()
        quadros.append(q)
        if q["tipo"] in ("fim_resposta", "erro"):
            return quadros


# ---------------------------------------------------------------------------- autenticação
def test_sem_autenticar_primeiro_nao_entra(client):
    with client.websocket_connect("/ws/voz") as ws:
        ws.send_json({"tipo": "texto", "texto": "oi"})
        assert ws.receive_json()["codigo"] == "nao_autenticado"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401


def test_token_falso_ou_perfil_sem_permissao_nao_entra(client):
    with client.websocket_connect("/ws/voz") as ws:
        ws.send_json({"tipo": "autenticar", "token": "lixo"})
        assert ws.receive_json()["codigo"] == "nao_autenticado"
    with client.websocket_connect("/ws/voz") as ws:  # a Vera é só leitura: não processa folha
        ws.send_json({"tipo": "autenticar", "token": token(client, "vera")})
        assert ws.receive_json()["codigo"] == "nao_autenticado"


def test_o_token_nao_vai_na_url_e_logout_derruba_o_acesso(client):
    h = entrar(client)
    t = h["Authorization"].split()[1]
    assert client.post("/logout", headers=h).status_code == 204
    with client.websocket_connect("/ws/voz") as ws:
        ws.send_json({"tipo": "autenticar", "token": t})
        assert ws.receive_json()["codigo"] == "nao_autenticado"


# ---------------------------------------------------------------------------- fala -> texto -> resposta
def test_fala_vira_transcricao_e_resposta_frase_por_frase_com_calculo_de_verdade(client):
    stt = STTFalso("calcular INSS")
    with voz(client, stt=stt) as ws:
        assert ws.pronto["stt"] is True and ws.pronto["persona"] == "MARIA_HELENA"
        falar(ws)
        quadros = receber_ate_o_fim(ws)
        assert quadros[0] == {"tipo": "transcricao", "texto": "calcular INSS"}
        assert stt.recebidos == [(b"abcdefghi", "fala.webm", "pt")]  # os três pedaços chegaram juntos e na ordem
        falas = [q for q in quadros if q["tipo"] == "fala"]
        fim = quadros[-1]
        assert falas and [f["n"] for f in falas] == list(range(1, len(falas) + 1))
        assert fim["tipo"] == "fim_resposta" and "salário" in fim["texto"].lower() and fim["sessao"]

        ws.send_json({"tipo": "texto", "texto": "salário de R$ 5.000,00", "sessao": fim["sessao"]})  # mesma conversa
        segunda = receber_ate_o_fim(ws)[-1]
        assert segunda["sessao"] == fim["sessao"] and "R$ 501,51" in segunda["texto"]  # INSS de 5.000 em 2026, conferido à mão
        assert segunda["tipo_calculo"] == "inss" and segunda["dados_calculados"]


def test_a_conversa_por_voz_fica_no_mesmo_historico_do_chat(client):
    with voz(client, stt=STTFalso("calcular INSS")) as ws:
        falar(ws)
        sid = receber_ate_o_fim(ws)[-1]["sessao"]
    r = client.get(f"/api/chat/{sid}", headers=entrar(client))
    assert r.status_code == 200 and "calcular INSS" in json.dumps(r.json())
    assert client.get(f"/api/chat/{sid}", headers=entrar(client, "joao")).status_code == 404  # e continua isolado por empresa


# ---------------------------------------------------------------------------- LGPD e configuração
def test_sem_consentimento_para_ia_externa_a_voz_e_recusada_mas_o_texto_funciona(client):
    client.app.state.lgpd.registrar_consentimento("empresa_a", None, "envio_a_provedor_de_ia", False, "teste")
    stt = STTFalso()
    with voz(client, stt=stt) as ws:
        falar(ws)
        assert ws.receive_json()["codigo"] == "sem_consentimento"
        assert stt.recebidos == []  # o áudio nem saiu do servidor
        ws.send_json({"tipo": "texto", "texto": "calcular INSS"})
        assert receber_ate_o_fim(ws)[-1]["tipo"] == "fim_resposta"


def test_sem_stt_configurado_a_voz_diz_o_que_falta(client):
    with voz(client, stt=None) as ws:
        assert ws.pronto["stt"] is False
        falar(ws)
        assert ws.receive_json()["codigo"] == "stt_indisponivel"


def test_fala_que_nao_se_entende_pede_para_repetir(client):
    with voz(client, stt=STTFalso("")) as ws:
        falar(ws)
        assert ws.receive_json()["codigo"] == "nao_entendi"


def test_falha_do_whisper_vira_erro_claro_e_a_conexao_continua(client):
    from contabil_agente.voz import STTIndisponivel

    class Quebrado:
        def transcrever(self, *a, **k):
            raise STTIndisponivel("whisper: ConnectError")

    with voz(client, stt=Quebrado()) as ws:
        falar(ws)
        assert ws.receive_json() == {"tipo": "erro", "codigo": "stt_falhou", "mensagem": "whisper: ConnectError"}
        ws.send_json({"tipo": "texto", "texto": "calcular INSS"})  # a conexão segue viva
        assert receber_ate_o_fim(ws)[-1]["tipo"] == "fim_resposta"


# ---------------------------------------------------------------------------- limites e protocolo
def test_protocolo_recusa_o_que_nao_faz_sentido_sem_derrubar_a_conexao(client):
    with voz(client, stt=STTFalso()) as ws:
        ws.send_bytes(b"audio sem inicio")
        assert ws.receive_json()["codigo"] == "sem_inicio"
        ws.send_text("isto nao e json")
        assert ws.receive_json()["codigo"] == "quadro_invalido"
        ws.send_json({"tipo": "voar"})
        assert ws.receive_json()["codigo"] == "tipo_desconhecido"
        ws.send_json({"tipo": "inicio", "formato": "exe"})
        assert ws.receive_json()["codigo"] == "formato_invalido"
        ws.send_json({"tipo": "fim"})
        assert ws.receive_json()["codigo"] == "audio_vazio"
        ws.send_json({"tipo": "texto", "texto": "x" * 4001})
        assert ws.receive_json()["codigo"] == "texto_invalido"
        ws.send_json({"tipo": "texto", "texto": "calcular INSS"})
        assert receber_ate_o_fim(ws)[-1]["tipo"] == "fim_resposta"


def test_fala_grande_demais_e_descartada(client, monkeypatch):
    import agente_v2.rotas_voz as rv

    monkeypatch.setattr(rv, "TAMANHO_MAXIMO_AUDIO", 1000)
    stt = STTFalso()
    with voz(client, stt=stt) as ws:
        ws.send_json({"tipo": "inicio"})
        ws.send_bytes(b"x" * 600)
        ws.send_bytes(b"x" * 600)
        assert ws.receive_json()["codigo"] == "audio_grande"
        ws.send_json({"tipo": "fim"})
        assert ws.receive_json()["codigo"] == "audio_vazio"  # depois do descarte, o "fim" não encontra áudio
    assert stt.recebidos == []


def test_cancelar_descarta_o_que_foi_gravado(client):
    stt = STTFalso()
    with voz(client, stt=stt) as ws:
        ws.send_json({"tipo": "inicio"})
        ws.send_bytes(b"abc")
        ws.send_json({"tipo": "cancelar"})
        ws.send_json({"tipo": "fim"})
        assert ws.receive_json()["codigo"] == "audio_vazio"
    assert stt.recebidos == []


# ---------------------------------------------------------------------------- auditoria
def test_auditoria_registra_a_mensagem_de_voz_sem_o_conteudo(client):
    with voz(client, stt=STTFalso("meu cpf é 529.982.247-25 e quero calcular férias")) as ws:
        falar(ws)
        receber_ate_o_fim(ws)
    trilha = json.dumps(client.app.state.audit.worm.ler("empresa_a"), ensure_ascii=False)
    assert "Mensagem de voz" in trilha and "bytes_de_audio" in trilha
    assert "529.982.247-25" not in trilha and "52998224725" not in trilha and "calcular férias" not in trilha


def test_se_a_auditoria_falhar_a_voz_nao_responde(client, monkeypatch):
    def quebra(*a, **k):
        raise AuditoriaError("disco cheio")

    with voz(client, stt=STTFalso()) as ws:  # o login já passou; só a gravação da fala na trilha vai falhar
        monkeypatch.setattr(client.app.state.audit, "log", quebra)
        falar(ws)
        quadros = receber_ate_o_fim(ws)
        assert quadros[-1]["codigo"] == "auditoria_indisponivel"
        assert not [q for q in quadros if q["tipo"] in ("fala", "fim_resposta")]  # nada foi falado sem a trilha


# ---------------------------------------------------------------------------- persona adaptativa
@pytest.mark.parametrize("texto,tom", [
    ("vc pode me explicar o que é aviso prévio, blz?", "informal"),
    ("Prezado, gostaria de saber o que é o aviso prévio.", "formal"),
    ("o que é aviso prévio", "base"),
])
def test_a_maria_helena_ajusta_o_tom_ao_jeito_de_quem_fala(client, llm, texto, tom):  # noqa: F811
    with voz(client, stt=None) as ws:
        ws.send_json({"tipo": "texto", "texto": texto})
        fim = receber_ate_o_fim(ws)[-1]
    assert fim["origem"] == "llm" and fim["persona"] == "MARIA_HELENA" and fim["tom"] == tom
    assert llm.recebido[-1][0]["content"] == obter_prompt("MARIA_HELENA", tom)  # e é o prompt daquele tom que foi para o modelo
