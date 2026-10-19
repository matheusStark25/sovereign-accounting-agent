"""Whisper (formato do pedido e limites, sem rede) e o tom adaptativo da assistente."""

import httpx
import pytest

from contabil_agente.chat.tom import escolher_variante
from contabil_agente.resilience import ChamadaResiliente
from contabil_agente.voz import MODELO_STT, STTIndisponivel, WhisperGroq, silencio_wav, stt_do_ambiente


def _cliente(capturar=None, status=200, corpo=None, rotas=None):
    def tratar(req):
        if capturar is not None:
            capturar.append(req)
        if rotas:
            return httpx.Response(200, json=rotas[req.url.path])
        return httpx.Response(status, json=corpo if corpo is not None else {"text": " Calcular rescisão "})

    return httpx.Client(transport=httpx.MockTransport(tratar))


def _whisper(**kw):
    return WhisperGroq("chave-secreta", resiliencia=ChamadaResiliente("w", tentativas=1, timeout=5, excecoes=(httpx.HTTPError, STTIndisponivel), dormir=lambda s: None), **kw)


# ----------------------------------------------------------------------------- Whisper
def test_pedido_ao_whisper_tem_o_formato_da_api_e_a_chave_so_no_cabecalho():
    pegos = []
    texto = _whisper(cliente=_cliente(pegos)).transcrever(b"RIFF....", "fala.webm", "pt")
    assert texto == "Calcular rescisão"  # sem os espaços das pontas
    req = pegos[0]
    assert req.url.path == "/openai/v1/audio/transcriptions" and req.headers["authorization"] == "Bearer chave-secreta"
    corpo = req.content
    assert b'name="model"' in corpo and MODELO_STT.encode() in corpo and b'name="language"' in corpo and b"pt" in corpo
    assert b'filename="fala.webm"' in corpo and b"audio/webm" in corpo and b"chave-secreta" not in corpo


def test_whisper_recusa_audio_vazio_grande_e_formato_estranho_sem_chamar_a_rede():
    pegos = []
    w = _whisper(cliente=_cliente(pegos))
    with pytest.raises(STTIndisponivel):
        w.transcrever(b"", "fala.webm")
    with pytest.raises(STTIndisponivel):
        w.transcrever(b"x" * (10 * 1024 * 1024 + 1), "fala.webm")
    with pytest.raises(STTIndisponivel) as e:
        w.transcrever(b"abc", "malware.exe")
    assert "exe" in str(e.value) and pegos == []


def test_erro_do_provedor_e_resposta_fora_do_formato_viram_stt_indisponivel():
    with pytest.raises(STTIndisponivel):
        _whisper(cliente=_cliente(status=401, corpo={"error": "chave"})).transcrever(b"abc", "fala.webm")
    with pytest.raises(STTIndisponivel):
        _whisper(cliente=_cliente(corpo={"sem_texto": 1})).transcrever(b"abc", "fala.webm")


def test_verificar_confere_chave_modelo_e_uma_transcricao_de_silencio():
    rotas = {"/openai/v1/models": {"data": [{"id": MODELO_STT}, {"id": "whisper-large-v3"}]}, "/openai/v1/audio/transcriptions": {"text": ""}}
    ok = _whisper(cliente=_cliente(rotas=rotas)).verificar()
    assert ok == {"provedor": "whisper", "modelo": MODELO_STT, "chave_valida": True, "modelo_existe": True, "chamada_ok": True}
    velho = _whisper(cliente=_cliente(rotas=rotas), modelo="whisper-v1").verificar()
    assert not velho["modelo_existe"] and "whisper-large-v3" in velho["alternativas"] and "whisper-v1" in velho["erro"]


def test_voz_sem_chave_fica_desligada_e_o_modelo_se_troca_por_ambiente():
    assert stt_do_ambiente({}) is None and stt_do_ambiente({"GROQ_API_KEY": "  "}) is None
    assert stt_do_ambiente({"GROQ_API_KEY": "k"}).modelo == MODELO_STT
    assert stt_do_ambiente({"GROQ_API_KEY": "k", "GROQ_STT_MODEL": "whisper-large-v3"}).modelo == "whisper-large-v3"
    with pytest.raises(STTIndisponivel):
        WhisperGroq("")


def test_silencio_wav_e_um_wav_valido():
    import io
    import wave

    with wave.open(io.BytesIO(silencio_wav(0.5))) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 8000)


# ----------------------------------------------------------------------------- tom adaptativo
@pytest.mark.parametrize("texto,tom", [
    ("vc pode me ajudar com as férias, blz?", "informal"),
    ("pq o INSS ta tao alto kkk", "informal"),
    ("PORRA NAO FUNCIONA ISSO AQUI", "informal"),
    ("Prezado, gostaria de saber o valor do 13º salário.", "formal"),
    ("Solicito, por gentileza, o cálculo da rescisão. Atenciosamente.", "formal"),
    ("quanto é o INSS de 3000", "base"),
    ("calcular rescisão admitido em 10/03/2023", "base"),
    ("", "base"),
])
def test_tom_por_marcas_claras(texto, tom):
    assert escolher_variante([texto]) == tom


def test_tom_acompanha_a_conversa_e_a_mensagem_mais_recente_pesa_mais():
    assert escolher_variante(["Prezado, gostaria de uma informação.", "blz, e vc sabe me dizer o 13º?"]) == "informal"
    assert escolher_variante(["blz vc ai?", "Prezado, gostaria de saber o prazo do aviso prévio."]) == "formal"
    assert escolher_variante(["oi", "quanto é o FGTS de 3000"]) == "base"
    assert escolher_variante(["vc pode?", "x", "y", "z"]) == "base"  # só as 3 últimas contam: a marca antiga saiu da janela
