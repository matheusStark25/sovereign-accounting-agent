"""Consentimento por titular (SQLite), com histórico e revogação, sem guardar o CPF em claro.

O titular é identificado por um hash HMAC do CPF/CNPJ (``PIIAnonymizer.hash_pii``). Consentimentos de
sistema (ex.: enviar texto a um provedor de IA) usam o titular ``*`` e valem para o tenant inteiro.
Cada mudança é um registro novo (histórico completo); o estado atual é o registro mais recente.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .anonimizacao import PIIAnonymizer
from .base_legal import finalidade

TITULAR_SISTEMA = "*"


class ConsentimentoStore:
    def __init__(self, db_path: str | Path, chave_hash: str):
        self.db_path = str(db_path)
        self._chave = chave_hash
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS consentimentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, titular TEXT NOT NULL, finalidade TEXT NOT NULL,
                    concedido INTEGER NOT NULL, texto_versao TEXT NOT NULL, ator TEXT NOT NULL, em REAL NOT NULL)"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS ix_cons ON consentimentos(tenant, titular, finalidade)")

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

    def identificar(self, documento_do_titular: Optional[str]) -> str:
        """``None`` ou ``*`` = consentimento de sistema; caso contrário, hash do CPF/CNPJ."""
        if documento_do_titular in (None, "", TITULAR_SISTEMA):
            return TITULAR_SISTEMA
        return PIIAnonymizer.hash_pii(documento_do_titular, self._chave)

    def registrar(self, tenant: str, titular: Optional[str], codigo_finalidade: str, concedido: bool, ator: str, texto_versao: str = "v1") -> int:
        finalidade(codigo_finalidade)  # recusa finalidade não cadastrada
        with self._db() as con:
            cur = con.execute(
                "INSERT INTO consentimentos (tenant, titular, finalidade, concedido, texto_versao, ator, em) VALUES (?,?,?,?,?,?,?)",
                (tenant, self.identificar(titular), codigo_finalidade, int(concedido), texto_versao, ator, time.time()),
            )
            return cur.lastrowid

    def ativo(self, tenant: str, titular: Optional[str], codigo_finalidade: str) -> bool:
        with self._db() as con:
            linha = con.execute(
                "SELECT concedido FROM consentimentos WHERE tenant=? AND titular=? AND finalidade=? ORDER BY id DESC LIMIT 1",
                (tenant, self.identificar(titular), codigo_finalidade),
            ).fetchone()
        return bool(linha and linha["concedido"])

    def historico(self, tenant: str, titular: Optional[str]) -> List[Dict[str, Any]]:
        with self._db() as con:
            linhas = con.execute(
                "SELECT finalidade, concedido, texto_versao, ator, em FROM consentimentos WHERE tenant=? AND titular=? ORDER BY id",
                (tenant, self.identificar(titular)),
            ).fetchall()
        return [{"finalidade": r["finalidade"], "concedido": bool(r["concedido"]), "versao": r["texto_versao"], "ator": r["ator"], "em": r["em"]} for r in linhas]

    def apagar_do_titular(self, tenant: str, titular: str) -> int:
        with self._db() as con:
            return con.execute("DELETE FROM consentimentos WHERE tenant=? AND titular=?", (tenant, self.identificar(titular))).rowcount
