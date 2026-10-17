"""Verificação cruzada: o ML-KEM-768 e o ML-DSA-65 usados pelo projeto (pacote ``cryptography``) contra duas
implementações independentes, escritas por outras pessoas (``kyber-py`` e ``dilithium-py``, só para teste).

Se as duas pontas discordassem em qualquer byte — chave derivada da mesma semente, segredo encapsulado ou
assinatura — o teste quebra. Concordar com uma segunda implementação do padrão FIPS 203/204 não é uma auditoria
formal, mas é uma prova concreta e repetível de que os bytes seguem o padrão.
"""

import os

import pytest
from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA65PrivateKey, MLDSA65PublicKey
from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey, MLKEM768PublicKey

ML_KEM_768 = pytest.importorskip("kyber_py.ml_kem").ML_KEM_768
ML_DSA_65 = pytest.importorskip("dilithium_py.ml_dsa").ML_DSA_65

SEMENTES = [os.urandom(64) for _ in range(3)] + [bytes(64), bytes(range(64))]


@pytest.mark.parametrize("semente", SEMENTES)
def test_mlkem_mesma_semente_mesma_chave_e_segredos_compativeis_nos_dois_sentidos(semente):
    ek_ref, dk_ref = ML_KEM_768.key_derive(semente)
    minha = MLKEM768PrivateKey.from_seed_bytes(semente)
    assert minha.public_key().public_bytes_raw() == ek_ref  # derivação da chave idêntica ao padrão

    # a implementação independente encapsula; a minha desencapsula
    segredo, ct = ML_KEM_768.encaps(ek_ref)
    assert minha.decapsulate(ct) == segredo

    # eu encapsulo; a independente desencapsula
    segredo2, ct2 = MLKEM768PublicKey.from_public_bytes(ek_ref).encapsulate()
    assert ML_KEM_768.decaps(dk_ref, ct2) == segredo2


def test_mlkem_texto_cifrado_adulterado_tem_rejeicao_implicita_igual_nas_duas():
    semente = os.urandom(64)
    _, dk_ref = ML_KEM_768.key_derive(semente)
    minha = MLKEM768PrivateKey.from_seed_bytes(semente)
    _, ct = MLKEM768PublicKey.from_public_bytes(minha.public_key().public_bytes_raw()).encapsulate()
    ruim = bytearray(ct)
    ruim[5] ^= 1
    # no ML-KEM não há erro: sai um segredo "falso" determinístico, e os dois têm de produzir o MESMO
    assert minha.decapsulate(bytes(ruim)) == ML_KEM_768.decaps(dk_ref, bytes(ruim))


@pytest.mark.parametrize("semente", [os.urandom(32) for _ in range(3)] + [bytes(32), bytes(range(32))])
def test_mldsa_mesma_semente_mesma_chave_e_assinaturas_aceitas_nos_dois_sentidos(semente):
    pk_ref, sk_ref = ML_DSA_65.key_derive(semente)
    minha = MLDSA65PrivateKey.from_seed_bytes(semente)
    assert minha.public_key().public_bytes_raw() == pk_ref

    msg = b"TRCT 09/2026 - liquido 10253.48"
    # a independente assina; eu verifico
    MLDSA65PublicKey.from_public_bytes(pk_ref).verify(ML_DSA_65.sign(sk_ref, msg), msg)
    # eu assino; a independente verifica
    assert ML_DSA_65.verify(pk_ref, msg, minha.sign(msg))
    # e nenhuma aceita assinatura para outra mensagem
    assert not ML_DSA_65.verify(pk_ref, msg + b"!", minha.sign(msg))


def test_mldsa_contexto_e_respeitado_pelas_duas():
    semente = os.urandom(32)
    pk_ref, sk_ref = ML_DSA_65.key_derive(semente)
    minha = MLDSA65PrivateKey.from_seed_bytes(semente)
    assert ML_DSA_65.verify(pk_ref, b"m", minha.sign(b"m", b"ctx"), ctx=b"ctx")
    assert not ML_DSA_65.verify(pk_ref, b"m", minha.sign(b"m", b"ctx"), ctx=b"outro")
    MLDSA65PublicKey.from_public_bytes(pk_ref).verify(ML_DSA_65.sign(sk_ref, b"m", ctx=b"ctx"), b"m", b"ctx")


def test_o_modulo_do_projeto_gera_chaves_que_a_implementacao_independente_aceita():
    from contabil_agente.security import pqc

    chaves = pqc.gerar_chaves_hibridas()
    segredo, ct = ML_KEM_768.encaps(chaves.kem_publica)
    assert MLKEM768PrivateKey.from_seed_bytes(chaves.kem_privada).decapsulate(ct) == segredo

    par = pqc.DilithiumAssinatura.gerar_par()
    assinatura = pqc.DilithiumAssinatura.assinar(par.privada, b"documento")
    assert ML_DSA_65.verify(par.publica, b"documento", assinatura)
