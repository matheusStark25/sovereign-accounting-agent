"""Governança de decisões críticas: assinatura digital, aprovação por limite de valor e trilha WORM.

* Toda decisão (rescisão, folha, cálculo especial...) é assinada com Dilithium (ML-DSA-65) sobre o seu
  conteúdo canônico; adulterar o valor no banco invalida a assinatura.
* Decisão com valor igual ou acima do limite do tipo fica ``PENDENTE`` até alguém APROVAR ou REJEITAR.
  Regra das duas pessoas: quem pediu não aprova a própria decisão.
* Cada passo (registro, aprovação, rejeição) entra na trilha WORM encadeada do tenant.
* Os limites são configuráveis (``GOVERNANCA_LIMITES``, JSON ou arquivo YAML); os padrões abaixo são só um ponto de partida.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import yaml

from contabil_agente.security import pqc
from contabil_agente.security.worm_audit import WormAudit

LIMITES_PADRAO: Dict[str, str] = {"rescisao": "50000.00", "folha": "200000.00", "ferias": "30000.00", "decimo_terceiro": "100000.00"}
PENDENTE, APROVADA, REJEITADA, AUTOMATICA = "PENDENTE", "APROVADA", "REJEITADA", "APROVADA_AUTOMATICAMENTE"


class GovernancaError(Exception):
    pass


class DecisaoNaoEncontrada(GovernancaError):
    pass


class RegraDasDuasPessoas(GovernancaError):
    """Quem solicitou a decisão não pode aprová-la."""


class DecisaoJaResolvida(GovernancaError):
    pass


class AssinaturaInvalida(GovernancaError):
    """A decisão no banco não bate com a assinatura: possível adulteração."""


def carregar_limites(origem: Optional[Mapping[str, Any] | str | Path] = None, env: Optional[Mapping[str, str]] = None) -> Dict[str, Decimal]:
    env = os.environ if env is None else env
    origem = origem if origem is not None else env.get("GOVERNANCA_LIMITES")
    dados: Dict[str, Any] = dict(LIMITES_PADRAO)
    if isinstance(origem, (str, Path)):
        texto = str(origem)
        if texto.strip().startswith("{"):
            dados.update(json.loads(texto))
        else:
            dados.update(yaml.safe_load(Path(texto).read_text(encoding="utf-8")) or {})
    elif origem:
        dados.update(origem)
    limites: Dict[str, Decimal] = {}
    for tipo, valor in dados.items():
        try:
            d = Decimal(str(valor))
        except InvalidOperation as exc:
            raise GovernancaError(f"Limite inválido para {tipo!r}: {valor!r}") from exc
        if d <= 0:
            raise GovernancaError(f"Limite de {tipo!r} deve ser maior que zero.")
        limites[tipo] = d
    return limites


def carregar_par_de_assinatura(segredos: Optional[Mapping[str, str]] = None, pasta_dev: Optional[Path] = None) -> pqc.ParDeChaves:
    """Par ML-DSA do ambiente/Vault (``GOVERNANCA_DSA_KEY``: JSON com ``pub`` e ``priv`` em base64).
    Só com ``AGENTE_ENV=dev`` um par é criado e guardado em ``pasta_dev``."""
    segredos = os.environ if segredos is None else segredos
    bruto = segredos.get("GOVERNANCA_DSA_KEY")
    if bruto:
        d = json.loads(bruto)
        return pqc.ParDeChaves(base64.b64decode(d["pub"]), base64.b64decode(d["priv"]))
    if segredos.get("AGENTE_ENV", "production").lower() != "dev" or pasta_dev is None:
        raise GovernancaError("Defina GOVERNANCA_DSA_KEY (gere com: python -m agente_v2.cli gerar-chave-governanca).")
    arq = pasta_dev / "governanca_dsa.json"
    if not arq.exists():
        par = pqc.DilithiumAssinatura.gerar_par()
        pasta_dev.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps({"pub": base64.b64encode(par.publica).decode(), "priv": base64.b64encode(par.privada).decode()}), encoding="utf-8")
        try:
            os.chmod(arq, 0o600)
        except OSError:
            pass
    d = json.loads(arq.read_text(encoding="utf-8"))
    return pqc.ParDeChaves(base64.b64decode(d["pub"]), base64.b64decode(d["priv"]))


@dataclass(frozen=True)
class Decisao:
    id: str
    tenant: str
    tipo: str
    valor: Decimal
    descricao: str
    referencia: str
    solicitante: str
    estado: str
    aprovador: Optional[str]
    comentario: str
    criado_em: float
    resolvido_em: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "tipo": self.tipo, "valor": str(self.valor), "descricao": self.descricao, "referencia": self.referencia,
            "solicitante": self.solicitante, "estado": self.estado, "aprovador": self.aprovador, "comentario": self.comentario,
            "criado_em": self.criado_em, "resolvido_em": self.resolvido_em,
        }


def _canonico(tenant: str, d: Mapping[str, Any]) -> bytes:
    nucleo = {k: d[k] for k in ("id", "tipo", "valor", "descricao", "referencia", "solicitante", "criado_em")}
    return json.dumps({"tenant": tenant, **nucleo}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class GovernanceManager:
    def __init__(self, db_path: str | Path, audit: WormAudit, par: pqc.ParDeChaves, limites: Optional[Mapping[str, Decimal]] = None):
        self.db_path, self.audit, self.par = str(db_path), audit, par
        self.limites = dict(limites) if limites is not None else carregar_limites(env={})
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS decisoes (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, tipo TEXT NOT NULL, valor TEXT NOT NULL, descricao TEXT NOT NULL,
                    referencia TEXT NOT NULL, solicitante TEXT NOT NULL, estado TEXT NOT NULL, aprovador TEXT, comentario TEXT NOT NULL DEFAULT '',
                    criado_em REAL NOT NULL, resolvido_em REAL, assinatura TEXT NOT NULL)"""
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ----------------------------------------------------------------- escrita
    def registrar(self, tenant: str, solicitante: str, tipo: str, valor: Decimal | str | float, descricao: str = "", referencia: str = "") -> Decisao:
        try:
            v = Decimal(str(valor))
        except InvalidOperation as exc:
            raise GovernancaError(f"Valor inválido: {valor!r}") from exc
        if v < 0:
            raise GovernancaError("O valor da decisão não pode ser negativo.")
        limite = self.limites.get(tipo)
        estado = PENDENTE if limite is not None and v >= limite else AUTOMATICA
        d = {"id": uuid.uuid4().hex, "tipo": tipo, "valor": str(v), "descricao": descricao[:300], "referencia": referencia[:120],
             "solicitante": solicitante, "criado_em": time.time()}
        assinatura = pqc.assinar_documento(self.par, _canonico(tenant, d))
        with self._db() as con:
            con.execute(
                "INSERT INTO decisoes (id, tenant, tipo, valor, descricao, referencia, solicitante, estado, criado_em, assinatura) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (d["id"], tenant, tipo, d["valor"], d["descricao"], d["referencia"], solicitante, estado, d["criado_em"], json.dumps(assinatura)),
            )
        self.audit.append("governanca.decisao_registrada", {"id": d["id"], "tipo": tipo, "valor": d["valor"], "estado": estado, "key_id": assinatura["key_id"]}, tenant=tenant, ator=solicitante)
        return self.obter(d["id"], tenant)

    def _resolver(self, decisao_id: str, tenant: str, aprovador: str, estado: str, comentario: str) -> Decisao:
        atual = self.obter(decisao_id, tenant)
        if atual.estado != PENDENTE:
            raise DecisaoJaResolvida(f"A decisão já está {atual.estado}.")
        if estado == APROVADA and aprovador == atual.solicitante:
            raise RegraDasDuasPessoas("Quem solicitou a decisão não pode aprová-la (regra das duas pessoas).")
        if not self.verificar_assinatura(decisao_id, tenant):
            self.audit.append("governanca.assinatura_invalida", {"id": decisao_id}, tenant=tenant, ator=aprovador)
            raise AssinaturaInvalida("A assinatura da decisão não confere: possível adulteração no banco.")
        with self._db() as con:
            con.execute(
                "UPDATE decisoes SET estado=?, aprovador=?, comentario=?, resolvido_em=? WHERE id=? AND tenant=? AND estado=?",
                (estado, aprovador, comentario[:300], time.time(), decisao_id, tenant, PENDENTE),
            )
        self.audit.append(f"governanca.decisao_{estado.lower()}", {"id": decisao_id, "tipo": atual.tipo, "valor": str(atual.valor)}, tenant=tenant, ator=aprovador)
        return self.obter(decisao_id, tenant)

    def aprovar(self, decisao_id: str, tenant: str, aprovador: str, comentario: str = "") -> Decisao:
        return self._resolver(decisao_id, tenant, aprovador, APROVADA, comentario)

    def rejeitar(self, decisao_id: str, tenant: str, aprovador: str, comentario: str = "") -> Decisao:
        return self._resolver(decisao_id, tenant, aprovador, REJEITADA, comentario)

    # ----------------------------------------------------------------- leitura
    @staticmethod
    def _decisao(r: sqlite3.Row) -> Decisao:
        return Decisao(r["id"], r["tenant"], r["tipo"], Decimal(r["valor"]), r["descricao"], r["referencia"], r["solicitante"], r["estado"],
                       r["aprovador"], r["comentario"], r["criado_em"], r["resolvido_em"])

    def obter(self, decisao_id: str, tenant: str) -> Decisao:
        with self._db() as con:
            r = con.execute("SELECT * FROM decisoes WHERE id = ? AND tenant = ?", (decisao_id, tenant)).fetchone()
        if r is None:
            raise DecisaoNaoEncontrada(decisao_id)
        return self._decisao(r)

    def pendentes(self, tenant: str) -> List[Decisao]:
        with self._db() as con:
            return [self._decisao(r) for r in con.execute("SELECT * FROM decisoes WHERE tenant = ? AND estado = ? ORDER BY criado_em", (tenant, PENDENTE))]

    def verificar_assinatura(self, decisao_id: str, tenant: str) -> bool:
        with self._db() as con:
            r = con.execute("SELECT * FROM decisoes WHERE id = ? AND tenant = ?", (decisao_id, tenant)).fetchone()
        if r is None:
            raise DecisaoNaoEncontrada(decisao_id)
        d = {"id": r["id"], "tipo": r["tipo"], "valor": r["valor"], "descricao": r["descricao"], "referencia": r["referencia"],
             "solicitante": r["solicitante"], "criado_em": r["criado_em"]}
        return pqc.verificar_documento(self.par.publica, _canonico(tenant, d), json.loads(r["assinatura"]))
