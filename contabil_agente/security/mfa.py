"""Verificação em duas etapas: TOTP (RFC 6238), o código de 6 dígitos dos aplicativos autenticadores.

* O segredo tem 160 bits (o tamanho recomendado pela RFC 4226) e fica CIFRADO no banco com AES-256-GCM. O id do usuário
  entra como dado associado: o segredo cifrado de um usuário não serve se for copiado para a linha de outro.
* Cada código vale por um passo de 30 segundos. Aceitamos o passo atual e um de cada lado (relógio do celular um pouco
  adiantado ou atrasado), e um código já usado não vale de novo: o último passo aceito fica guardado (contra repetição).
* Códigos de recuperação: 10, de uso único, guardados como HMAC-SHA256 (nunca em claro).
* A implementação é conferida contra os vetores de teste das RFCs 4226 e 6238 (``tests/test_mfa.py``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import List, Optional
from urllib.parse import quote, urlencode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PASSO_SEGUNDOS = 30
DIGITOS = 6
TOLERANCIA_PASSOS = 1
EMISSOR = "Sovereign Accounting Agent"
QUANTIDADE_RECUPERACAO = 10
_ALFABETO_RECUPERACAO = "abcdefghjkmnpqrstuvwxyz23456789"  # sem 0/o nem 1/l/i, que se confundem no papel
# HMAC-SHA1 é o algoritmo da RFC 6238 e o único que todos os aplicativos autenticadores aceitam; HMAC-SHA1 continua seguro
# (o ataque de colisão ao SHA-1 não se aplica ao HMAC). SHA-256 e SHA-512 ficam para os vetores de teste da RFC.
_ALGORITMOS = {"sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}


class SegredoInvalido(ValueError):
    """O segredo cifrado não abre (chave trocada ou linha do banco adulterada)."""


def gerar_segredo() -> str:
    """Segredo novo em Base32, o formato que os aplicativos autenticadores leem."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def chave_do_segredo(segredo_b32: str) -> bytes:
    limpo = "".join(str(segredo_b32).split()).upper()
    return base64.b32decode(limpo + "=" * (-len(limpo) % 8))


def hotp(chave: bytes, contador: int, digitos: int = DIGITOS, algoritmo: str = "sha1") -> str:
    """HOTP (RFC 4226): HMAC do contador, truncamento dinâmico e os últimos ``digitos`` dígitos."""
    mac = hmac.new(chave, struct.pack(">Q", contador), _ALGORITMOS[algoritmo]).digest()
    deslocamento = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** digitos).zfill(digitos)


def passo(instante: Optional[float] = None, passo_segundos: int = PASSO_SEGUNDOS) -> int:
    return int((time.time() if instante is None else instante) // passo_segundos)


def totp(segredo_b32: str, instante: Optional[float] = None, digitos: int = DIGITOS) -> str:
    """O código do momento (o mesmo que o aplicativo do celular mostra)."""
    return hotp(chave_do_segredo(segredo_b32), passo(instante), digitos)


def conferir_totp(segredo_b32: str, codigo: str, instante: Optional[float] = None, ultimo_passo: int = 0,
                  tolerancia: int = TOLERANCIA_PASSOS) -> Optional[int]:
    """O passo em que ``codigo`` vale (para guardar e não aceitar de novo) ou ``None``.

    Passos iguais ou anteriores a ``ultimo_passo`` já foram usados e não valem mais.
    """
    digitado = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(digitado) != DIGITOS:
        return None
    chave, atual = chave_do_segredo(segredo_b32), passo(instante)
    achado = None
    for p in range(atual - tolerancia, atual + tolerancia + 1):
        # sem parar no primeiro acerto: o tempo de resposta não revela qual passo bateu
        if hmac.compare_digest(hotp(chave, p), digitado) and p > ultimo_passo:
            achado = p
    return achado


def uri_de_configuracao(segredo_b32: str, conta: str, emissor: str = EMISSOR) -> str:
    """``otpauth://`` que o aplicativo autenticador lê pelo QR code (formato do Google Authenticator)."""
    parametros = urlencode({"secret": segredo_b32, "issuer": emissor, "algorithm": "SHA1", "digits": DIGITOS,
                            "period": PASSO_SEGUNDOS}, quote_via=quote)
    return f"otpauth://totp/{quote(emissor)}:{quote(conta)}?{parametros}"


def qr_code(texto: str) -> Optional[str]:
    """QR code em SVG (``data:image/svg+xml``), gerado no servidor: a página não carrega nada de fora."""
    try:
        import segno
    except ImportError:  # sem a biblioteca, a tela mostra só o segredo para digitar no aplicativo
        return None
    return segno.make(texto, error="m").svg_data_uri(scale=5, border=2)


def gerar_codigos_de_recuperacao(quantidade: int = QUANTIDADE_RECUPERACAO) -> List[str]:
    """Códigos como ``k7m2p-x9qrt``: cerca de 50 bits cada, para usar uma vez se o celular sumir."""
    return ["-".join("".join(secrets.choice(_ALFABETO_RECUPERACAO) for _ in range(5)) for _ in range(2))
            for _ in range(quantidade)]


def normalizar_recuperacao(codigo: str) -> str:
    return "".join(ch for ch in str(codigo or "").lower() if ch.isascii() and ch.isalnum())


def parece_codigo_de_recuperacao(codigo: str) -> bool:
    return len(normalizar_recuperacao(codigo)) == 10


class CifraDeSegredos:
    """AES-256-GCM para o segredo TOTP no banco e HMAC para os códigos de recuperação.

    As duas chaves saem do mesmo material (``MFA_ENCRYPTION_KEY`` ou, sem ela, o ``JWT_SECRET``) por HKDF-SHA256 com rótulos
    diferentes: uma chave nunca é usada para dois fins.
    """

    def __init__(self, material: str | bytes):
        bruto = material.encode("utf-8") if isinstance(material, str) else material
        if len(bruto) < 32:
            raise ValueError("A chave da verificação em duas etapas precisa ter pelo menos 32 caracteres.")
        self._aes = AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"sovereign-mfa-totp-v1").derive(bruto))
        self._hmac = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"sovereign-mfa-recuperacao-v1").derive(bruto)

    def cifrar(self, texto: str, contexto: str) -> str:
        nonce = os.urandom(12)
        return base64.urlsafe_b64encode(nonce + self._aes.encrypt(nonce, texto.encode("utf-8"), contexto.encode("utf-8"))).decode("ascii")

    def decifrar(self, cifrado: str, contexto: str) -> str:
        try:
            bruto = base64.urlsafe_b64decode(cifrado.encode("ascii"))
            return self._aes.decrypt(bruto[:12], bruto[12:], contexto.encode("utf-8")).decode("utf-8")
        except (InvalidTag, ValueError) as exc:
            raise SegredoInvalido("O segredo da verificação em duas etapas não confere (chave trocada ou dado adulterado).") from exc

    def hash_recuperacao(self, codigo: str) -> str:
        return hmac.new(self._hmac, b"recuperacao|" + normalizar_recuperacao(codigo).encode("ascii"), hashlib.sha256).hexdigest()
