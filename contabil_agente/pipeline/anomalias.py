"""Detector de anomalias: duplicidade, repetição de competência, valores atípicos e valores impossíveis.

O histórico fica em SQLite, separado por tenant. O valor atípico usa escore z robusto (mediana e MAD),
que não se deixa enganar por um outlier antigo, e só dispara com pelo menos 5 observações anteriores.
"""

from __future__ import annotations

import sqlite3
import json
import statistics
import time
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from contabil_agente.documentos.tipos import Alerta

METRICA = {
    "HOLERITE": "total_proventos", "DARF": "total", "GPS": "total", "NFE_XML": "valor_nota", "DAS": "valor",
    "FGTS_GUIA": "valor_fgts", "TRCT": "liquido", "RECIBO_FERIAS": "liquido",
    "INFORME_RENDIMENTOS": "rendimentos_tributaveis", "NFSE": "valor_servicos",
}
MINIMO_OBSERVACOES = 5
LIMITE_Z = 3.5


def _dec(valor: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return None


def _cnpj_do(dados: Dict[str, Any]) -> str:
    for chave in ("cnpj", "emitente_cnpj", "cnpj_fonte_pagadora", "cnpj_prestador", "cnpj_empregador", "inscricao_empregador"):
        if dados.get(chave):
            return str(dados[chave])
    return ""


class HistoricoDocumentos:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS processados (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, sha256 TEXT NOT NULL, tipo TEXT NOT NULL,
                    cnpj TEXT NOT NULL, competencia TEXT NOT NULL, valor TEXT, audit_id TEXT, criado_em REAL NOT NULL)"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS ix_proc_hash ON processados(tenant, sha256)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_proc_chave ON processados(tenant, tipo, cnpj)")
            colunas = {linha["name"] for linha in con.execute("PRAGMA table_info(processados)")}
            if "resumo" not in colunas:  # bancos criados antes da memória da assistente
                con.execute("ALTER TABLE processados ADD COLUMN resumo TEXT")

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

    def registrar(self, tenant: str, sha256: str, tipo: str, dados: Dict[str, Any], audit_id: Optional[str],
                  resumo: Optional[Dict[str, Any]] = None) -> None:
        """``resumo``: o que a assistente pode consultar depois (já com dados pessoais mascarados por quem chama)."""
        campo = METRICA.get(tipo)
        with self._db() as con:
            con.execute(
                "INSERT INTO processados (tenant, sha256, tipo, cnpj, competencia, valor, audit_id, criado_em, resumo) VALUES (?,?,?,?,?,?,?,?,?)",
                (tenant, sha256, tipo, _cnpj_do(dados), str(dados.get("competencia") or dados.get("periodo_apuracao") or ""),
                 str(dados[campo]) if campo and campo in dados else None, audit_id, time.time(),
                 json.dumps(resumo, ensure_ascii=False, default=str) if resumo else None),
            )

    def recentes(self, tenant: str, limite: int = 10) -> List[Dict[str, Any]]:
        """Os últimos documentos processados da empresa, do mais novo para o mais antigo (só desta empresa)."""
        with self._db() as con:
            linhas = con.execute(
                "SELECT id, sha256, tipo, cnpj, competencia, valor, criado_em, resumo FROM processados WHERE tenant=? ORDER BY id DESC LIMIT ?",
                (tenant, max(1, min(int(limite), 50))),
            ).fetchall()
        saida = []
        for r in linhas:
            item = {"id": r["id"], "tipo": r["tipo"], "cnpj": r["cnpj"] or None, "competencia": r["competencia"] or None, "valor": r["valor"],
                    "processado_em": time.strftime("%d/%m/%Y %H:%M", time.localtime(r["criado_em"])), "sha256": r["sha256"][:12]}
            if r["resumo"]:
                try:
                    item.update(json.loads(r["resumo"]))
                except ValueError:
                    pass
            saida.append(item)
        return saida

    def por_hash(self, tenant: str, sha256: str) -> Optional[sqlite3.Row]:
        with self._db() as con:
            return con.execute("SELECT * FROM processados WHERE tenant=? AND sha256=? ORDER BY id LIMIT 1", (tenant, sha256)).fetchone()

    def por_chave(self, tenant: str, tipo: str, cnpj: str, competencia: str) -> List[sqlite3.Row]:
        with self._db() as con:
            return con.execute(
                "SELECT * FROM processados WHERE tenant=? AND tipo=? AND cnpj=? AND competencia=?", (tenant, tipo, cnpj, competencia)
            ).fetchall()

    def valores(self, tenant: str, tipo: str, cnpj: str) -> List[Decimal]:
        with self._db() as con:
            linhas = con.execute("SELECT valor FROM processados WHERE tenant=? AND tipo=? AND cnpj=? AND valor IS NOT NULL", (tenant, tipo, cnpj)).fetchall()
        return [d for d in (_dec(r["valor"]) for r in linhas) if d is not None]

    def apagar_do_tenant(self, tenant: str) -> int:
        with self._db() as con:
            return con.execute("DELETE FROM processados WHERE tenant=?", (tenant,)).rowcount


def z_robusto(valor: Decimal, historico: List[Decimal]) -> Optional[float]:
    if len(historico) < MINIMO_OBSERVACOES:
        return None
    xs = [float(x) for x in historico]
    mediana = statistics.median(xs)
    mad = statistics.median([abs(x - mediana) for x in xs])
    if mad == 0:
        return None if float(valor) == mediana else (float("inf") if abs(float(valor) - mediana) > 0.5 * abs(mediana or 1) else 0.0)
    return 0.6745 * (float(valor) - mediana) / mad


class DetectorDeAnomalias:
    def __init__(self, historico: HistoricoDocumentos):
        self.historico = historico

    def avaliar(self, tenant: str, tipo: str, dados: Dict[str, Any], sha256: str, hoje: Optional[date] = None) -> List[Alerta]:
        hoje = hoje or date.today()
        alertas: List[Alerta] = []
        anterior = self.historico.por_hash(tenant, sha256)
        if anterior is not None:
            alertas.append(Alerta("documento_duplicado", f"Este arquivo já foi processado (trilha {anterior['audit_id']}).", "aviso"))
        comp = str(dados.get("competencia") or dados.get("periodo_apuracao") or "")
        cnpj = _cnpj_do(dados)
        if comp and cnpj:
            outros = [r for r in self.historico.por_chave(tenant, tipo, cnpj, comp) if r["sha256"] != sha256]
            if outros:
                alertas.append(Alerta("competencia_repetida", f"Já existe {len(outros)} documento(s) {tipo} desta empresa na competência {comp} (retificação ou duplicidade).", "aviso"))
        campo = METRICA.get(tipo)
        valor = _dec(dados.get(campo)) if campo else None
        if valor is not None and cnpj:
            if valor == 0:
                alertas.append(Alerta("valor_zerado", f"{campo} é zero.", "aviso"))
            z = z_robusto(valor, self.historico.valores(tenant, tipo, cnpj))
            if z is not None and abs(z) >= LIMITE_Z:
                alertas.append(Alerta("valor_atipico", f"{campo}={valor} foge do padrão histórico desta empresa (escore robusto {z:.1f}).", "aviso"))
        alertas += self._regras(tipo, dados, hoje)
        return alertas

    @staticmethod
    def _regras(tipo: str, d: Dict[str, Any], hoje: date) -> List[Alerta]:
        alertas: List[Alerta] = []
        comp = d.get("competencia") or d.get("periodo_apuracao")
        if isinstance(comp, str) and len(comp) >= 7 and comp[4] == "-":
            try:
                ano, mes = int(comp[:4]), int(comp[5:7])
                inicio = date(ano, mes, 1)
                if inicio > hoje + timedelta(days=31):
                    alertas.append(Alerta("competencia_futura", f"A competência {comp} é posterior ao mês atual.", "erro"))
                elif inicio < date(hoje.year - 5, hoje.month, 1):
                    alertas.append(Alerta("competencia_antiga", f"A competência {comp} tem mais de 5 anos (prazo prescricional).", "aviso"))
            except ValueError:
                alertas.append(Alerta("competencia_invalida", f"Competência inválida: {comp}.", "erro"))
        if tipo == "HOLERITE":
            prov, inss, irrf = _dec(d.get("total_proventos")), _dec(d.get("inss")), _dec(d.get("irrf"))
            if prov and prov > 0:
                if inss is not None and inss > prov * Decimal("0.14") + Decimal("0.01"):
                    alertas.append(Alerta("inss_acima_do_maximo", "INSS acima de 14% dos proventos, o máximo da tabela.", "erro"))
                if irrf is not None and irrf > prov * Decimal("0.275") + Decimal("0.01"):
                    alertas.append(Alerta("irrf_acima_do_maximo", "IRRF acima de 27,5% dos proventos, a maior alíquota.", "erro"))
        return alertas
