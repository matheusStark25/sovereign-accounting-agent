"""Kyber (ML-KEM-768) e Dilithium (ML-DSA-65) de verdade: tamanhos do padrão, ida e volta e adulteração."""

import copy

import pytest

from contabil_agente.security import pqc


@pytest.fixture(scope="module")
def chaves():
    return pqc.gerar_chaves_hibridas()


@pytest.fixture(scope="module")
def par():
    return pqc.DilithiumAssinatura.gerar_par()


def test_tamanhos_batem_com_o_padrao_fips_203_e_204(chaves, par):
    assert len(chaves.kem_publica) == 1184 and len(chaves.kem_privada) == 64  # semente (FIPS 203, d||z)
    assert len(par.publica) == 1952 and len(par.privada) == 32  # semente (FIPS 204, xi)
    envelope = pqc.cifrar_hibrido(chaves.publica(), b"x")
    assert len(pqc._unb64(envelope["kem_ct"])) == 1088
    assert len(pqc._unb64(pqc.assinar_documento(par, b"x")["assinatura"])) == 3309


def test_cifra_e_decifra_dados(chaves):
    dado = "folha de pagamento 09/2026 — Líquido R$ 4.973,39".encode()
    env = pqc.cifrar_hibrido(chaves.publica(), dado, aad=b"tenant:empresa_a")
    assert dado not in str(env).encode() and env["alg"] == "ML-KEM-768+X25519"
    assert pqc.decifrar_hibrido(chaves.privada(), env, aad=b"tenant:empresa_a") == dado


def test_cada_cifragem_e_diferente(chaves):
    a = pqc.cifrar_hibrido(chaves.publica(), b"igual")
    b = pqc.cifrar_hibrido(chaves.publica(), b"igual")
    assert a["ct"] != b["ct"] and a["kem_ct"] != b["kem_ct"]


def test_contexto_aad_diferente_falha(chaves):
    env = pqc.cifrar_hibrido(chaves.publica(), b"segredo", aad=b"A")
    with pytest.raises(pqc.PQCError):
        pqc.decifrar_hibrido(chaves.privada(), env, aad=b"B")


def test_chave_errada_nao_decifra(chaves):
    outra = pqc.gerar_chaves_hibridas()
    env = pqc.cifrar_hibrido(chaves.publica(), b"segredo")
    with pytest.raises(pqc.PQCError):
        pqc.decifrar_hibrido(outra.privada(), env)


@pytest.mark.parametrize("campo", ["ct", "nonce", "kem_ct", "x25519_efemera"])
def test_envelope_adulterado_e_recusado(chaves, campo):
    env = pqc.cifrar_hibrido(chaves.publica(), b"segredo")
    adulterado = copy.deepcopy(env)
    bruto = bytearray(pqc._unb64(adulterado[campo]))
    bruto[0] ^= 0x01
    adulterado[campo] = pqc._b64(bytes(bruto))
    with pytest.raises((pqc.PQCError, ValueError)):
        pqc.decifrar_hibrido(chaves.privada(), adulterado)


def test_envelope_incompleto_ou_de_outro_algoritmo(chaves):
    env = pqc.cifrar_hibrido(chaves.publica(), b"x")
    sem = {k: v for k, v in env.items() if k != "nonce"}
    with pytest.raises(pqc.PQCError):
        pqc.decifrar_hibrido(chaves.privada(), sem)
    with pytest.raises(pqc.PQCError):
        pqc.decifrar_hibrido(chaves.privada(), {**env, "alg": "RSA"})
    with pytest.raises(pqc.PQCError):
        pqc.cifrar_hibrido({**chaves.publica(), "alg": "RSA"}, b"x")


def test_base64_invalido_e_chave_publica_curta(chaves):
    env = pqc.cifrar_hibrido(chaves.publica(), b"x")
    with pytest.raises(pqc.PQCError):
        pqc.decifrar_hibrido(chaves.privada(), {**env, "ct": "###"})
    with pytest.raises(pqc.PQCError):
        pqc.cifrar_hibrido({**chaves.publica(), "kem": pqc._b64(b"curta")}, b"x")


def test_assinatura_verifica_e_detecta_falsificacao(par):
    msg = b"TRCT assinado"
    sig = pqc.DilithiumAssinatura.assinar(par.privada, msg)
    assert pqc.DilithiumAssinatura.verificar(par.publica, msg, sig)
    assert not pqc.DilithiumAssinatura.verificar(par.publica, b"TRCT assinadO", sig)
    ruim = bytearray(sig)
    ruim[10] ^= 1
    assert not pqc.DilithiumAssinatura.verificar(par.publica, msg, bytes(ruim))
    outro = pqc.DilithiumAssinatura.gerar_par()
    assert not pqc.DilithiumAssinatura.verificar(outro.publica, msg, sig)


def test_assinatura_malformada_nao_levanta():
    assert pqc.DilithiumAssinatura.verificar(b"x", b"m", b"s") is False
    assert pqc.DilithiumAssinatura.verificar(b"\x00" * 1952, b"m", b"\x00" * 3309) is False


def test_pacote_de_assinatura_de_documento(par):
    dados = b"%PDF-1.4 conteudo do documento"
    pacote = pqc.assinar_documento(par, dados)
    assert pacote["alg"] == "ML-DSA-65" and pacote["key_id"] == par.id
    assert pqc.verificar_documento(par.publica, dados, pacote)
    assert not pqc.verificar_documento(par.publica, dados + b"x", pacote)
    assert not pqc.verificar_documento(par.publica, dados, {**pacote, "key_id": "outra"})
    assert not pqc.verificar_documento(par.publica, dados, {**pacote, "alg": "RSA"})
    assert not pqc.verificar_documento(par.publica, dados, {"alg": "ML-DSA-65", "key_id": par.id})


def test_ids_de_chave_sao_estaveis_e_distintos(chaves, par):
    assert chaves.id == pqc.key_id(chaves.kem_publica + chaves.x25519_publica)
    assert chaves.publica()["id"] == chaves.id and par.id != chaves.id
