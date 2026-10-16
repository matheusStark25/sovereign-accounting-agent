"""Orquestrador, TaxEngine e ComplianceChecker sobre o motor real (sem stub)."""

import asyncio
import time
from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.intelligence.calculator import TaxEngine
from contabil_agente.intelligence.compliance import ComplianceChecker
from contabil_agente.intelligence.orchestrator import IntelligenceOrchestrator, mesclar_fontes
from contabil_agente.utils.documentos import cnpj_valido, cpf_valido

HOJE = date(2026, 10, 15)


@pytest.fixture
def orq(tmp_path):
    return IntelligenceOrchestrator(db_path=str(tmp_path / "cache.sqlite"), hoje=HOJE)


def rodar(coro):
    return asyncio.run(coro)


# -------------------------------------------------------------- TaxEngine
def test_tax_engine_usa_tabelas_2026_e_nao_inventa_fgts():
    r = TaxEngine(HOJE).calculate({"amount": 3000})
    assert r["inss"] == 248.60
    assert r["irrf"] == 0.0
    assert r["salario_liquido"] == 2751.40
    assert r["fgts_mensal"] == 240.00  # 8% exato
    assert r["ferias_integral"] == 4000.00
    assert r["decimo_terceiro_proporcional"] == 3000.00
    assert "saldo_fgts_estimado" not in r and "multa_fgts_40" not in r  # nada de estimativa


def test_tax_engine_rejeita_salario_invalido():
    from contabil_agente.calc import DadosInvalidos

    with pytest.raises(DadosInvalidos):
        TaxEngine(HOJE).calculate({"amount": 0})
    with pytest.raises(DadosInvalidos):
        TaxEngine(HOJE).calculate({"amount": "abc"})


# -------------------------------------------------------------- documentos
def test_cpf_e_cnpj():
    assert cpf_valido("529.982.247-25") and not cpf_valido("529.982.247-24")
    assert not cpf_valido("111.111.111-11")
    assert cnpj_valido("11.222.333/0001-81") and not cnpj_valido("11.222.333/0001-80")


# ------------------------------------------------------------- compliance
def test_compliance_bloqueia_cpf_invalido_e_salario_abaixo_do_minimo():
    c = ComplianceChecker()
    r = c.validate({"cpf": "111.111.111-11", "salario": 1000, "date": "2026-10-01"})
    campos = {i["field"] for i in r["issues"]}
    assert r["ok"] is False and campos == {"cpf", "salario"}


def test_compliance_usa_o_salario_minimo_das_tabelas_2026():
    c = ComplianceChecker()
    assert c.validate({"salario": 1621, "date": "2026-10-01"})["ok"] is True
    assert c.validate({"salario": 1620.99, "date": "2026-10-01"})["ok"] is False  # mínimo de 2026 = 1.621,00


def test_compliance_alerta_rescisao_alta():
    c = ComplianceChecker()
    r = c.validate({"salario": 9000}, {"tipo": "rescisao", "total_proventos": 20000.0, "total_descontos": 1000.0, "total_liquido": 19000.0})
    assert r["ok"] is True and any(a["field"] == "rescisao" for a in r["alerts"])


def test_compliance_bloqueia_liquido_negativo():
    c = ComplianceChecker()
    r = c.validate({"salario": 3000}, {"total_liquido": -10.0})
    assert r["ok"] is False


# ------------------------------------------------------------ orquestrador
def test_mesclar_fontes_peso_e_recencia():
    fontes = [
        {"data": {"salario": 1000, "nome": "A"}, "weight": 0.5, "timestamp": 1},
        {"data": {"salario": 2000}, "weight": 0.9, "timestamp": 1},
        {"data": {"salario": 3000}, "weight": 0.9, "timestamp": 5},
    ]
    assert mesclar_fontes(fontes) == {"salario": 3000, "nome": "A"}


def test_orquestrador_calcula_inss_de_verdade(orq):
    r = rodar(orq.handle("s1", {"tipo_calculo": "inss", "sources": [{"data": {"salario": 5000}, "weight": 0.9, "timestamp": time.time()}]}))
    assert r["status"] == "ok"
    assert r["calc"]["inss"] == 501.51  # e nunca "o valor recebido devolvido como total"
    assert r["comp"]["ok"] is True
    estados = [h["to"] for h in r["fsm"]]
    assert estados[-1] == "FINALIZADO" and "CALCULANDO" in estados


def test_orquestrador_so_com_valor_usa_o_tax_engine(orq):
    r = rodar(orq.handle("s2", {"amount": 3000, "date": "2026-10-15"}))
    assert r["status"] == "ok" and r["calc"]["inss"] == 248.60


def test_orquestrador_pede_o_que_falta_em_vez_de_calcular_errado(orq):
    r = rodar(orq.handle("s3", {"tipo_calculo": "rescisao", "sources": [{"data": {"salario": 3000}, "weight": 0.9}]}))
    assert r["status"] == "needs_manual_input"
    assert "data_admissao" in r["faltando"] and "tipo_rescisao" in r["faltando"]
    assert r["fsm"][-1]["to"] == "AGUARDANDO_INPUT"


def test_orquestrador_rescisao_completa(orq):
    dados = {"salario": 3000, "tipo_rescisao": "sem_justa_causa", "data_admissao": "2023-03-10",
             "data_demissao": "2026-09-15", "aviso_previo": "indenizado", "saldo_fgts": 12000}
    r = rodar(orq.handle("s4", {"tipo_calculo": "rescisao", "sources": [{"data": dados, "weight": 0.9}]}))
    assert r["status"] == "ok"
    assert r["calc"]["total_liquido"] == 10253.48
    assert r["calc"]["fgts"]["multa"] == 5052.80
    assert "Líquido a receber" in r["calc"]["resumo"]


def test_orquestrador_bloqueia_dados_invalidos(orq):
    r = rodar(orq.handle("s5", {"tipo_calculo": "inss", "sources": [{"data": {"salario": 3000, "cpf": "123.456.789-00"}, "weight": 0.9}]}))
    assert r["status"] == "needs_manual_input" and r["issues"][0]["field"] == "cpf"


def test_orquestrador_erro_de_calculo_nao_vira_zero(orq):
    r = rodar(orq.handle("s6", {"tipo_calculo": "inss", "date": "2024-01-10", "sources": [{"data": {"salario": 3000, "date": "2024-01-10", "competencia": "2024-01-01"}, "weight": 0.9}]}))
    assert r["status"] == "error" and "tabela" in r["error"].lower()


def test_orquestrador_audita_cada_pedido(orq, tmp_path):
    r = rodar(orq.handle("s7", {"amount": 3000}))
    assert r["request_id"]
    assert orq.audit.log_path.exists()
