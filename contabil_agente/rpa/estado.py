"""Status dos trabalhos do RPA (SQLite), sempre por tenant. Nunca guarda CPF: só o hash do titular."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

ENFILEIRADO = "ENFILEIRADO"
EXECUTANDO = "EXECUTANDO"
AGUARDANDO_HUMANO = "AGUARDANDO_HUMANO"
CONCLUIDO = "CONCLUIDO"
FALHOU = "FALHOU"
ESTADOS = (ENFILEIRADO, EXECUTANDO, AGUARDANDO_HUMANO, CONCLUIDO, FALHOU)
TERMINAIS = (CONCLUIDO, FALHOU)


class StatusStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS rpa_jobs (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, ator TEXT NOT NULL, tarefa TEXT NOT NULL, titular TEXT,
                    estado TEXT NOT NULL, mensagem TEXT NOT NULL DEFAULT '', resultado TEXT, criado_em REAL NOT NULL, atualizado_em REAL NOT NULL)"""
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

    def criar(self, tenant: str, ator: str, tarefa: str, titular_hash: Optional[str] = None) -> str:
        job_id = uuid.uuid4().hex
        agora = time.time()
        with self._db() as con:
            con.execute(
                "INSERT INTO rpa_jobs (id, tenant, ator, tarefa, titular, estado, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?)",
                (job_id, tenant, ator, tarefa, titular_hash, ENFILEIRADO, agora, agora),
            )
        return job_id

    def atualizar(self, job_id: str, estado: str, mensagem: str = "", resultado: Optional[Dict[str, Any]] = None) -> None:
        if estado not in ESTADOS:
            raise ValueError(f"Estado inválido: {estado}")
        with self._db() as con:
            atual = con.execute("SELECT estado FROM rpa_jobs WHERE id = ?", (job_id,)).fetchone()
            if atual is None:
                raise KeyError(job_id)
            if atual["estado"] in TERMINAIS:
                return  # estado final não volta atrás
            con.execute(
                "UPDATE rpa_jobs SET estado=?, mensagem=?, resultado=?, atualizado_em=? WHERE id=?",
                (estado, mensagem[:500], json.dumps(resultado, ensure_ascii=False, default=str) if resultado is not None else None, time.time(), job_id),
            )

    def obter(self, job_id: str, tenant: str) -> Optional[Dict[str, Any]]:
        with self._db() as con:
            r = con.execute("SELECT * FROM rpa_jobs WHERE id = ? AND tenant = ?", (job_id, tenant)).fetchone()
        if r is None:
            return None
        return {
            "id": r["id"], "tarefa": r["tarefa"], "estado": r["estado"], "mensagem": r["mensagem"],
            "resultado": json.loads(r["resultado"]) if r["resultado"] else None,
            "criado_em": r["criado_em"], "atualizado_em": r["atualizado_em"],
        }

    def apagar_do_titular(self, tenant: str, titular_hash: str) -> int:
        with self._db() as con:
            return con.execute("DELETE FROM rpa_jobs WHERE tenant = ? AND titular = ?", (tenant, titular_hash)).rowcount
