import pytest

from contabil_agente.chat import ChatEngine
from contabil_agente.core.prompts import REGRAS_FIXAS, obter_prompt, personas_disponiveis


@pytest.mark.parametrize("persona", ["MARCOS", "MARIA_HELENA", "maria helena"])
def test_toda_persona_leva_as_regras_fixas(persona):
    assert obter_prompt(persona).endswith(REGRAS_FIXAS)


def test_marcos_tem_tres_variantes():
    base, formal, informal = (obter_prompt("MARCOS", v) for v in ("base", "formal", "informal"))
    assert len({base, formal, informal}) == 3


def test_nenhuma_persona_manda_fingir_ser_humano_ou_infalivel():
    for persona in personas_disponiveis():
        for variante in ("base", "formal", "informal"):
            texto = obter_prompt(persona, variante).lower()
            assert "não é ia" not in texto and "infalível" not in texto and "nunca diga 'sou uma ia'" not in texto
            assert "ia" in texto and "assistente virtual" in texto


def test_persona_ou_variante_desconhecida():
    with pytest.raises(ValueError):
        obter_prompt("JOSE")
    with pytest.raises(ValueError):
        obter_prompt("MARCOS", "debochado")


def test_engine_manda_o_prompt_da_persona_ao_llm():
    recebido = []
    engine = ChatEngine(llm=lambda m: recebido.append(m) or "ok", persona="MARIA_HELENA")
    engine.responder({}, "explique o que é o DARF")
    assert recebido[0][0]["role"] == "system" and "Auditoria Sênior" in recebido[0][0]["content"]
    marcos = []
    ChatEngine(llm=lambda m: marcos.append(m) or "ok").responder({}, "explique o que é o DARF")
    assert "MARCOS" in marcos[0][0]["content"]
