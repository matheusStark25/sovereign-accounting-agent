"""Trilha de auditoria WORM (write once, read many) com encadeamento HMAC-SHA256.

Cada entrada guarda o HMAC da entrada anterior (``prev``) e o seu próprio (``hash``), calculado
sobre o conteúdo inteiro. Por isso:

* alterar qualquer campo de uma entrada quebra o ``hash`` dela;
* apagar, inserir ou reordenar entradas quebra o ``prev`` da seguinte;
* cortar o final do arquivo é detectado pelo arquivo ``.head`` (também assinado), que guarda a
  última sequência e o último hash.

Limites honestos: quem tem acesso de escrita ao disco E à chave HMAC pode refazer a cadeia, e
quem restaura juntos o arquivo e o ``.head`` antigos não é detectado sem uma âncora externa
(``ancora()`` devolve o necessário para gravar o cabeçalho em outro sistema). O arquivo só é aberto
em modo de acréscimo, com permissão 0600 quando o sistema operacional permite; para imutabilidade
imposta pelo sistema use volume append-only (``chattr +a``) ou armazenamento de objetos com retenção.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import portalocker

from contabil_agente.middleware.lgpd import PIIAnonymizer

logger = logging.getLogger(__name__)

GENESIS = "0" * 64
_TENANT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
CHAVE_MINIMA = 32


class AuditoriaError(RuntimeError):
    """Falha ao gravar a trilha de auditoria (nunca é engolida em silêncio)."""


@dataclass(frozen=True)
class Recibo:
    tenant: str
    seq: int
    hash: str

    @property
    def id(self) -> str:
        return f"{self.tenant}:{self.seq}:{self.hash[:16]}"


@dataclass
class Verificacao:
    tenant: str
    entradas: int = 0
    problemas: List[str] = field(default_factory=list)
    head_seq: Optional[int] = None
    head_hash: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.problemas

    def to_dict(self) -> Dict[str, Any]:
        return {"tenant": self.tenant, "entradas": self.entradas, "ok": self.ok, "problemas": self.problemas,
                "head_seq": self.head_seq, "head_hash": self.head_hash}


def _canonico(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sanear(valor: Any) -> Any:
    """Mascara CPF, CNPJ, e-mail, telefone e cartão em qualquer texto aninhado."""
    if isinstance(valor, str):
        return PIIAnonymizer.anonymize_text(valor)
    if isinstance(valor, Mapping):
        return {str(k): _sanear(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_sanear(v) for v in valor]
    return valor


class WormAudit:
    def __init__(self, diretorio: str | Path, chave: str | bytes, fsync: bool = True, mascarar_pii: bool = True):
        bruta = chave.encode("utf-8") if isinstance(chave, str) else chave
        if len(bruta) < CHAVE_MINIMA:
            raise ValueError(f"A chave HMAC da auditoria precisa ter pelo menos {CHAVE_MINIMA} bytes.")
        self._chave = bruta
        self.dir = Path(diretorio)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync
        self._mascarar = mascarar_pii

    # ------------------------------------------------------------------ chave
    @classmethod
    def do_ambiente(cls, diretorio: str | Path, env: Optional[Mapping[str, str]] = None, **kw) -> "WormAudit":
        """Chave em ``AUDIT_HMAC_KEY`` (obrigatória). Só com ``AGENTE_ENV=dev`` gera e guarda uma em ``.audit_key``."""
        env = os.environ if env is None else env
        chave = env.get("AUDIT_HMAC_KEY", "")
        if not chave:
            if env.get("AGENTE_ENV", "production").lower() != "dev":
                raise ValueError("Defina AUDIT_HMAC_KEY (mínimo 32 caracteres) para a trilha de auditoria.")
            arq = Path(diretorio) / ".audit_key"
            Path(diretorio).mkdir(parents=True, exist_ok=True)
            if not arq.exists():
                arq.write_text(secrets.token_hex(32), encoding="ascii")
                _restringir(arq)
                logger.warning("AUDIT_HMAC_KEY ausente: chave de desenvolvimento criada em %s", arq)
            chave = arq.read_text(encoding="ascii").strip()
        return cls(diretorio, chave, **kw)

    # ---------------------------------------------------------------- caminhos
    def _caminho(self, tenant: str) -> Path:
        if not _TENANT_RE.match(tenant or "") or tenant in (".", ".."):
            raise ValueError(f"Tenant inválido para a auditoria: {tenant!r}")
        return self.dir / f"{tenant}.worm.jsonl"

    def _head_path(self, tenant: str) -> Path:
        return self._caminho(tenant).with_suffix(".head")

    # ------------------------------------------------------------------ cripto
    def _mac(self, prev: str, corpo: Dict[str, Any]) -> str:
        return hmac.new(self._chave, (prev + "|" + _canonico(corpo)).encode("utf-8"), hashlib.sha256).hexdigest()

    def _mac_head(self, seq: int, h: str) -> str:
        return hmac.new(self._chave, f"head|{seq}|{h}".encode("utf-8"), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ escrita
    @staticmethod
    def _ultima_entrada(caminho: Path) -> Optional[Dict[str, Any]]:
        if not caminho.exists() or caminho.stat().st_size == 0:
            return None
        with open(caminho, "rb") as f:
            f.seek(0, os.SEEK_END)
            fim = f.tell()
            bloco = min(fim, 65536)
            f.seek(fim - bloco)
            linhas = f.read(bloco).splitlines()
        for linha in reversed(linhas):
            if linha.strip():
                return json.loads(linha)
        return None

    def append(self, evento: str, dados: Optional[Mapping[str, Any]] = None, tenant: str = "SYSTEM", ator: str = "sistema") -> Recibo:
        caminho = self._caminho(tenant)
        if self._mascarar:
            dados = _sanear(dados or {})
        try:
            with portalocker.Lock(str(caminho) + ".lock", timeout=10):
                ultima = self._ultima_entrada(caminho)
                seq = 1 if ultima is None else ultima["seq"] + 1
                prev = GENESIS if ultima is None else ultima["hash"]
                corpo = {
                    "seq": seq,
                    "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "tenant": tenant,
                    "ator": str(ator),
                    "evento": str(evento),
                    "dados": dict(dados or {}),
                    "prev": prev,
                }
                entrada = {**corpo, "hash": self._mac(prev, corpo)}
                novo = not caminho.exists()
                with open(caminho, "a", encoding="utf-8", newline="\n") as f:
                    f.write(_canonico(entrada) + "\n")
                    f.flush()
                    if self._fsync:
                        os.fsync(f.fileno())
                if novo:
                    _restringir(caminho)
                self._gravar_head(tenant, seq, entrada["hash"])
        except portalocker.exceptions.LockException as exc:
            raise AuditoriaError("Não consegui o bloqueio de escrita da trilha de auditoria.") from exc
        except OSError as exc:
            raise AuditoriaError(f"Falha ao gravar a trilha de auditoria: {exc}") from exc
        return Recibo(tenant, seq, entrada["hash"])

    def _gravar_head(self, tenant: str, seq: int, h: str) -> None:
        destino = self._head_path(tenant)
        temp = destino.with_suffix(".head.tmp")
        temp.write_text(_canonico({"seq": seq, "hash": h, "mac": self._mac_head(seq, h)}), encoding="utf-8")
        _restringir(temp)
        os.replace(temp, destino)

    # ------------------------------------------------------------------ leitura
    def ler(self, tenant: str, inicio: int = 1, limite: int = 1000) -> List[Dict[str, Any]]:
        caminho = self._caminho(tenant)
        if not caminho.exists():
            return []
        saida: List[Dict[str, Any]] = []
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                if not linha.strip():
                    continue
                entrada = json.loads(linha)
                if entrada["seq"] >= inicio:
                    saida.append(entrada)
                if len(saida) >= limite:
                    break
        return saida

    def tenants(self) -> List[str]:
        return sorted(p.name[: -len(".worm.jsonl")] for p in self.dir.glob("*.worm.jsonl"))

    # -------------------------------------------------------------- verificação
    def verificar(self, tenant: str) -> Verificacao:
        r = Verificacao(tenant)
        caminho = self._caminho(tenant)
        if not caminho.exists():
            if self._head_path(tenant).exists():
                r.problemas.append("O arquivo da trilha foi removido (o ponteiro .head ainda existe).")
            return r
        prev, esperado = GENESIS, 1
        with open(caminho, "r", encoding="utf-8") as f:
            for n, linha in enumerate(f, 1):
                if not linha.strip():
                    r.problemas.append(f"Linha {n}: linha em branco inesperada.")
                    continue
                try:
                    entrada = json.loads(linha)
                    h = entrada.pop("hash")
                except (ValueError, KeyError):
                    r.problemas.append(f"Linha {n}: entrada ilegível ou sem hash.")
                    prev = None
                    continue
                if entrada.get("seq") != esperado:
                    r.problemas.append(f"Linha {n}: sequência {entrada.get('seq')} (esperada {esperado}): entrada removida, inserida ou reordenada.")
                if prev is not None and entrada.get("prev") != prev:
                    r.problemas.append(f"Linha {n}: não encadeia com a entrada anterior.")
                if not hmac.compare_digest(h, self._mac(entrada.get("prev", ""), entrada)):
                    r.problemas.append(f"Linha {n}: conteúdo adulterado (HMAC não confere).")
                prev, esperado = h, (entrada.get("seq") or esperado) + 1
                r.entradas += 1
                r.head_seq, r.head_hash = entrada.get("seq"), h
        head = self._ler_head(tenant)
        if head is None:
            r.problemas.append("Ponteiro .head ausente ou inválido: não dá para provar que o final não foi cortado.")
        else:
            if head["seq"] != r.head_seq or head["hash"] != r.head_hash:
                r.problemas.append(f"O .head aponta para a sequência {head['seq']}, mas a trilha termina em {r.head_seq}: entradas removidas do final ou arquivo restaurado.")
        return r

    def _ler_head(self, tenant: str) -> Optional[Dict[str, Any]]:
        try:
            head = json.loads(self._head_path(tenant).read_text(encoding="utf-8"))
            if hmac.compare_digest(head["mac"], self._mac_head(head["seq"], head["hash"])):
                return head
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def ancora(self, tenant: str) -> Dict[str, Any]:
        """Cabeçalho assinado para gravar fora do servidor (e-mail, outro sistema, carimbo de tempo)."""
        head = self._ler_head(tenant)
        if head is None:
            raise AuditoriaError("Sem cabeçalho válido para ancorar.")
        return {"tenant": tenant, "seq": head["seq"], "hash": head["hash"], "gerado_em": int(time.time())}


def _restringir(caminho: Path) -> None:
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass  # Windows e alguns sistemas de arquivos
