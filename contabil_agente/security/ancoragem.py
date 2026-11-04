"""Âncora externa da trilha de auditoria: fecha a porta que a trilha sozinha deixa aberta.

A trilha WORM (``worm_audit.py``) acusa qualquer byte mudado, mas quem tem o disco E a chave HMAC consegue refazer a cadeia
inteira, e quem restaura juntos o arquivo e o ``.head`` de um backup antigo volta no tempo sem deixar rastro. A âncora
resolve isso: de tempos em tempos, o cabeçalho da trilha (a sequência e o hash da última entrada) é publicado num lugar que
este servidor não consegue reescrever. Na conferência, cada âncora publicada tem de bater com a entrada daquela sequência:

* cadeia refeita com a chave: o hash da entrada ancorada muda, e a âncora acusa;
* trilha cortada ou restaurada de um backup antigo: a sequência ancorada some ou o hash não bate.

Destinos (um ou os dois, configurados pelo ambiente):

* ``AUDIT_ANCHOR_DIR``: diretório em OUTRO volume ou máquina (compartilhamento de rede, disco com ``chattr +a``, bucket
  montado com retenção/Object Lock). Uma linha JSON por âncora, só acréscimo. Não pode ficar dentro da pasta da trilha.
* ``AUDIT_ANCHOR_URL`` (com ``AUDIT_ANCHOR_TOKEN``): serviço HTTPS que guarda as âncoras (outro sistema da empresa, um log de
  transparência). ``POST`` com a âncora em JSON grava; ``GET ?tenant=<empresa>`` devolve a lista para a conferência.

Publicar: ``python -m agente_v2.cli ancorar-auditoria`` (agende de hora em hora no cron ou no agendador de tarefas) ou
``POST /api/v1/auditoria/ancorar``. Conferir: ``python -m agente_v2.cli conferir-ancoras`` ou ``GET /api/v1/auditoria/verificar``.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlparse

import httpx

from .worm_audit import AuditoriaError, WormAudit

logger = logging.getLogger(__name__)

_TENANT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ErroDeAncora(RuntimeError):
    """Não deu para publicar ou ler as âncoras no destino externo."""


class DestinoDeAncora(Protocol):
    nome: str

    def publicar(self, ancora: Dict[str, Any]) -> Dict[str, Any]: ...

    def listar(self, tenant: str) -> List[Dict[str, Any]]: ...


def _validar_tenant(tenant: str) -> str:
    if not _TENANT_RE.match(tenant or "") or tenant in (".", ".."):
        raise ValueError(f"Tenant inválido para a âncora: {tenant!r}")
    return tenant


class AncoraEmDiretorio:
    """Âncoras num diretório de outro volume: um arquivo ``<tenant>.ancoras.jsonl`` por empresa, só acréscimo."""

    nome = "diretorio"

    def __init__(self, diretorio: str | Path):
        self.dir = Path(diretorio)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _arquivo(self, tenant: str) -> Path:
        return self.dir / f"{_validar_tenant(tenant)}.ancoras.jsonl"

    def publicar(self, ancora: Dict[str, Any]) -> Dict[str, Any]:
        arquivo = self._arquivo(ancora["tenant"])
        linha = (json.dumps(ancora, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            fd = os.open(arquivo, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, linha)
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise ErroDeAncora(f"Não consegui gravar a âncora em {arquivo}: {exc}") from exc
        return {"destino": self.nome, "arquivo": str(arquivo)}

    def listar(self, tenant: str) -> List[Dict[str, Any]]:
        arquivo = self._arquivo(tenant)
        if not arquivo.exists():
            return []
        saida = []
        for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if not linha.strip():
                continue
            try:
                saida.append(json.loads(linha))
            except ValueError as exc:
                raise ErroDeAncora(f"Linha {n} de {arquivo.name} ilegível.") from exc
        return saida


class AncoraHTTP:
    """Âncoras num serviço HTTPS de fora: ``POST`` grava, ``GET ?tenant=`` lista."""

    nome = "http"

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 10.0, transport: Any = None):
        u = urlparse(url)
        local = u.hostname in ("localhost", "127.0.0.1", "::1")
        if u.scheme != "https" and not (u.scheme == "http" and local):
            raise ValueError("AUDIT_ANCHOR_URL precisa ser HTTPS (http só para localhost, em teste).")
        self.url, self._token = url, token
        self._cliente = httpx.Client(timeout=timeout, transport=transport)

    def _cabecalhos(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def publicar(self, ancora: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = self._cliente.post(self.url, json=ancora, headers=self._cabecalhos())
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ErroDeAncora(f"O serviço de âncoras recusou ou não respondeu ({type(exc).__name__}).") from exc
        return {"destino": self.nome, "status": r.status_code}

    def listar(self, tenant: str) -> List[Dict[str, Any]]:
        try:
            r = self._cliente.get(self.url, params={"tenant": _validar_tenant(tenant)}, headers=self._cabecalhos())
            r.raise_for_status()
            dados = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ErroDeAncora(f"Não consegui ler as âncoras do serviço ({type(exc).__name__}).") from exc
        itens = dados.get("ancoras") if isinstance(dados, dict) else dados
        if not isinstance(itens, list):
            raise ErroDeAncora("O serviço de âncoras não devolveu uma lista.")
        return [a for a in itens if isinstance(a, dict) and a.get("tenant") == tenant]


@dataclass
class ConferenciaDeAncoras:
    tenant: str
    destino: str
    conferidas: int = 0
    ultima_seq: Optional[int] = None
    problemas: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemas

    def to_dict(self) -> Dict[str, Any]:
        return {"destino": self.destino, "ok": self.ok, "conferidas": self.conferidas, "ultima_seq": self.ultima_seq,
                "problemas": self.problemas}


def _quando(ancora: Mapping[str, Any]) -> str:
    try:
        return datetime.fromtimestamp(int(ancora.get("gerado_em")), timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "data desconhecida"


class Ancorador:
    """Publica o cabeçalho da trilha nos destinos externos e confere a trilha local contra o que foi publicado."""

    def __init__(self, worm: WormAudit, destinos: Sequence[DestinoDeAncora]):
        if not destinos:
            raise ValueError("Informe ao menos um destino para as âncoras.")
        self.worm, self.destinos = worm, list(destinos)

    def ancorar(self, tenant: str) -> Dict[str, Any]:
        verificacao = self.worm.verificar(tenant)
        if not verificacao.ok:  # ancorar uma trilha adulterada seria dar a ela um selo de confiança
            raise AuditoriaError(f"A trilha de {tenant} não está íntegra, não publiquei a âncora: {verificacao.problemas[0]}")
        ancora = self.worm.ancora(tenant)
        recibos, erros = [], []
        for destino in self.destinos:
            try:
                recibos.append(destino.publicar(ancora))
            except ErroDeAncora as exc:
                erros.append(f"{destino.nome}: {exc}")
                logger.error("Âncora de %s não publicada em %s: %s", tenant, destino.nome, exc)
        if not recibos:
            raise ErroDeAncora("; ".join(erros))
        return {"ancora": ancora, "recibos": recibos, "erros": erros}

    def ancorar_todos(self) -> List[Dict[str, Any]]:
        saida = []
        for tenant in self.worm.tenants():
            try:
                saida.append({"tenant": tenant, **self.ancorar(tenant)})
            except (AuditoriaError, ErroDeAncora) as exc:
                saida.append({"tenant": tenant, "erro": str(exc)})
        return saida

    def conferir(self, tenant: str) -> List[ConferenciaDeAncoras]:
        """Para cada destino: toda âncora publicada tem de existir na trilha com o mesmo hash."""
        hashes = {e["seq"]: e["hash"] for e in self.worm.ler(tenant, limite=10**9)}
        fim = max(hashes) if hashes else 0
        resultado = []
        for destino in self.destinos:
            c = ConferenciaDeAncoras(tenant, destino.nome)
            try:
                ancoras = destino.listar(tenant)
            except ErroDeAncora as exc:
                c.problemas.append(f"Não consegui ler as âncoras ({destino.nome}): {exc}")
                resultado.append(c)
                continue
            for a in ancoras:
                seq, h = a.get("seq"), a.get("hash")
                if not isinstance(seq, int) or not isinstance(h, str):
                    c.problemas.append("Âncora sem sequência ou hash válidos.")
                    continue
                c.conferidas += 1
                c.ultima_seq = max(c.ultima_seq or 0, seq)
                if seq not in hashes:
                    c.problemas.append(f"A entrada {seq}, ancorada em {_quando(a)}, não existe mais (a trilha termina em {fim}): "
                                       "trilha cortada ou restaurada de um backup antigo.")
                elif not hmac.compare_digest(hashes[seq], h):
                    c.problemas.append(f"A entrada {seq} foi reescrita depois de ancorada em {_quando(a)}: o hash não é o publicado.")
            resultado.append(c)
        return resultado


def ancoragem_do_ambiente(worm: WormAudit, env: Optional[Mapping[str, str]] = None) -> Optional[Ancorador]:
    """O ``Ancorador`` configurado por ``AUDIT_ANCHOR_DIR`` e/ou ``AUDIT_ANCHOR_URL``; ``None`` se nenhum estiver definido."""
    env = os.environ if env is None else env
    destinos: List[DestinoDeAncora] = []
    pasta = (env.get("AUDIT_ANCHOR_DIR") or "").strip()
    if pasta:
        alvo, trilha = Path(pasta).resolve(), worm.dir.resolve()
        if alvo == trilha or trilha in alvo.parents:
            raise ValueError("AUDIT_ANCHOR_DIR não pode ficar dentro da pasta da trilha: a âncora precisa estar em outro lugar.")
        destinos.append(AncoraEmDiretorio(alvo))
    url = (env.get("AUDIT_ANCHOR_URL") or "").strip()
    if url:
        destinos.append(AncoraHTTP(url, (env.get("AUDIT_ANCHOR_TOKEN") or "").strip() or None))
    return Ancorador(worm, destinos) if destinos else None
