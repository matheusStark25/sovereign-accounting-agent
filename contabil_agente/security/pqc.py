"""Criptografia pós-quântica: Kyber (ML-KEM-768, FIPS 203) e Dilithium (ML-DSA-65, FIPS 204).

* ``cifrar_hibrido`` combina ML-KEM-768 com X25519 (o segredo final sai de HKDF-SHA256 sobre os dois):
  quem quebrar só um dos algoritmos ainda não lê o dado. A cifra de dados é AES-256-GCM.
* ``DilithiumAssinatura`` assina e verifica com ML-DSA-65.

Aviso: as implementações de ML-KEM/ML-DSA vêm de ``kyber-py`` e ``dilithium-py``, em Python puro. São
corretas (os tamanhos e os testes de ida e volta seguem o padrão), mas NÃO são de tempo constante e são
lentas; para produção com adversário na mesma máquina troque por ``liboqs``. A interface deste módulo
não muda com a troca.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from dilithium_py.ml_dsa import ML_DSA_65
from kyber_py.ml_kem import ML_KEM_768

ALG_KEM = "ML-KEM-768+X25519"
ALG_ASSINATURA = "ML-DSA-65"
TAMANHOS = {"kem_pk": 1184, "kem_sk": 2400, "kem_ct": 1088, "dsa_pk": 1952, "dsa_sk": 4032, "dsa_sig": 3309}
INFO_HKDF = b"sovereign-accounting-agent/hybrid-kem/v1"


class PQCError(Exception):
    """Falha criptográfica: dado adulterado, chave errada ou envelope inválido."""


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    try:
        return base64.b64decode(s.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise PQCError("Base64 inválido no envelope.") from exc


def key_id(chave_publica: bytes) -> str:
    return hashlib.sha256(chave_publica).hexdigest()[:16]


@dataclass(frozen=True)
class ParDeChaves:
    publica: bytes
    privada: bytes

    @property
    def id(self) -> str:
        return key_id(self.publica)


# --------------------------------------------------------------- KEM híbrido
@dataclass(frozen=True)
class ChavesHibridas:
    kem_publica: bytes
    kem_privada: bytes
    x25519_publica: bytes
    x25519_privada: bytes

    @property
    def id(self) -> str:
        return key_id(self.kem_publica + self.x25519_publica)

    def publica(self) -> Dict[str, str]:
        return {"alg": ALG_KEM, "kem": _b64(self.kem_publica), "x25519": _b64(self.x25519_publica), "id": self.id}

    def privada(self) -> Dict[str, str]:
        return {"alg": ALG_KEM, "kem": _b64(self.kem_privada), "x25519": _b64(self.x25519_privada), "id": self.id}


def gerar_chaves_hibridas() -> ChavesHibridas:
    pk, sk = ML_KEM_768.keygen()
    x = X25519PrivateKey.generate()
    return ChavesHibridas(
        pk, sk,
        x.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
        x.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()),
    )


def _derivar(segredo_pq: bytes, segredo_x: bytes, contexto: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO_HKDF + contexto).derive(segredo_pq + segredo_x)


def cifrar_hibrido(chave_publica: Dict[str, str], dados: bytes, aad: bytes = b"") -> Dict[str, str]:
    """Cifra ``dados`` para o dono da chave pública. ``aad`` é autenticado junto (e tem de ser o mesmo ao decifrar)."""
    if chave_publica.get("alg") != ALG_KEM:
        raise PQCError(f"Algoritmo não suportado: {chave_publica.get('alg')!r}.")
    pk_kem, pk_x = _unb64(chave_publica["kem"]), _unb64(chave_publica["x25519"])
    if len(pk_kem) != TAMANHOS["kem_pk"]:
        raise PQCError("Chave pública ML-KEM com tamanho inválido.")
    segredo_pq, kem_ct = ML_KEM_768.encaps(pk_kem)
    efemera = X25519PrivateKey.generate()
    efemera_pub = efemera.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    segredo_x = efemera.exchange(X25519PublicKey.from_public_bytes(pk_x))
    chave = _derivar(segredo_pq, segredo_x, kem_ct + efemera_pub)
    nonce = os.urandom(12)
    cifrado = AESGCM(chave).encrypt(nonce, dados, aad)
    return {"alg": ALG_KEM, "kem_ct": _b64(kem_ct), "x25519_efemera": _b64(efemera_pub), "nonce": _b64(nonce), "ct": _b64(cifrado), "key_id": chave_publica.get("id", "")}


def decifrar_hibrido(chave_privada: Dict[str, str], envelope: Dict[str, str], aad: bytes = b"") -> bytes:
    if envelope.get("alg") != ALG_KEM or chave_privada.get("alg") != ALG_KEM:
        raise PQCError("Algoritmo do envelope ou da chave não suportado.")
    try:
        kem_ct, efemera_pub = _unb64(envelope["kem_ct"]), _unb64(envelope["x25519_efemera"])
        nonce, cifrado = _unb64(envelope["nonce"]), _unb64(envelope["ct"])
        sk_kem, sk_x = _unb64(chave_privada["kem"]), _unb64(chave_privada["x25519"])
    except KeyError as exc:
        raise PQCError(f"Envelope incompleto: falta {exc.args[0]}.") from exc
    if len(kem_ct) != TAMANHOS["kem_ct"]:
        raise PQCError("Texto cifrado ML-KEM com tamanho inválido.")
    segredo_pq = ML_KEM_768.decaps(sk_kem, kem_ct)
    segredo_x = X25519PrivateKey.from_private_bytes(sk_x).exchange(X25519PublicKey.from_public_bytes(efemera_pub))
    chave = _derivar(segredo_pq, segredo_x, kem_ct + efemera_pub)
    try:
        return AESGCM(chave).decrypt(nonce, cifrado, aad)
    except InvalidTag as exc:
        raise PQCError("Falha na autenticação: dado adulterado, chave errada ou contexto (aad) diferente.") from exc


# --------------------------------------------------------------- assinatura
class DilithiumAssinatura:
    algoritmo = ALG_ASSINATURA

    @staticmethod
    def gerar_par() -> ParDeChaves:
        pk, sk = ML_DSA_65.keygen()
        return ParDeChaves(pk, sk)

    @staticmethod
    def assinar(chave_privada: bytes, mensagem: bytes) -> bytes:
        if len(chave_privada) != TAMANHOS["dsa_sk"]:
            raise PQCError("Chave privada ML-DSA com tamanho inválido.")
        return ML_DSA_65.sign(chave_privada, mensagem)

    @staticmethod
    def verificar(chave_publica: bytes, mensagem: bytes, assinatura: bytes) -> bool:
        if len(chave_publica) != TAMANHOS["dsa_pk"] or len(assinatura) != TAMANHOS["dsa_sig"]:
            return False
        try:
            return bool(ML_DSA_65.verify(chave_publica, mensagem, assinatura))
        except Exception:  # noqa: BLE001 - assinatura malformada nunca deve levantar para o chamador
            return False


def assinar_documento(par: ParDeChaves, dados: bytes) -> Dict[str, str]:
    """Assina o SHA-256 dos dados e devolve um pacote verificável (algoritmo, id da chave e assinatura)."""
    resumo = hashlib.sha256(dados).digest()
    return {"alg": ALG_ASSINATURA, "key_id": par.id, "sha256": resumo.hex(), "assinatura": _b64(DilithiumAssinatura.assinar(par.privada, resumo))}


def verificar_documento(chave_publica: bytes, dados: bytes, pacote: Dict[str, str]) -> bool:
    if pacote.get("alg") != ALG_ASSINATURA or pacote.get("key_id") != key_id(chave_publica):
        return False
    resumo = hashlib.sha256(dados).digest()
    if pacote.get("sha256") != resumo.hex():
        return False
    try:
        return DilithiumAssinatura.verificar(chave_publica, resumo, _unb64(pacote["assinatura"]))
    except (PQCError, KeyError):
        return False


def par_de_bytes(publica: bytes, privada: bytes) -> Tuple[bytes, bytes]:
    return publica, privada
