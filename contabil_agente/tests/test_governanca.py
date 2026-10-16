"""Governança: decisões assinadas, aprovação por limite, duas pessoas, adulteração e redação de logs."""

import json
import logging
import sqlite3
from decimal import Decimal

import pytest

from contabil_agente.governance import RedactionFilter, instalar_filtro_de_redacao
from contabil_agente.governance_manager import (
    APROVADA,
    AUTOMATICA,
    PENDENTE,
    REJEITADA,
    AssinaturaInvalida,
    DecisaoJaResolvida,
    DecisaoNaoEncontrada,
    GovernanceManager,
    GovernancaError,
    RegraDasDuasPessoas,
    carregar_limites,
    carregar_par_de_assinatura,
)
from contabil_agente.security import pqc
from contabil_agente.security.worm_audit import WormAudit


@pytest.fixture(scope="module")
def par():
    return pqc.DilithiumAssinatura.gerar_par()


@pytest.fixture()
def gov(tmp_path, par):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    return GovernanceManager(tmp_path / "gov.db", audit, par, {"rescisao": Decimal("50000")})


def test_abaixo_do_limite_e_aprovada_automaticamente_e_assinada(gov):
    d = gov.registrar("t1", "maria", "rescisao", "10253.48", "rescisão de teste", "TRCT-1")
    assert d.estado == AUTOMATICA and d.valor == Decimal("10253.48")
    assert gov.verificar_assinatura(d.id, "t1") is True


def test_tipo_sem_limite_nunca_pede_aprovacao(gov):
    assert gov.registrar("t1", "maria", "tipo_sem_limite", "9999999").estado == AUTOMATICA


def test_no_limite_ou_acima_fica_pendente(gov):
    assert gov.registrar("t1", "maria", "rescisao", "50000.00").estado == PENDENTE
    assert gov.registrar("t1", "maria", "rescisao", "49999.99").estado == AUTOMATICA
    assert len(gov.pendentes("t1")) == 1


def test_regra_das_duas_pessoas(gov):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    with pytest.raises(RegraDasDuasPessoas):
        gov.aprovar(d.id, "t1", "maria")
    ok = gov.aprovar(d.id, "t1", "joao", "conferido")
    assert ok.estado == APROVADA and ok.aprovador == "joao" and ok.comentario == "conferido" and ok.resolvido_em
    assert gov.pendentes("t1") == []


def test_o_solicitante_pode_rejeitar_a_propria_decisao(gov):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    assert gov.rejeitar(d.id, "t1", "maria", "errei o valor").estado == REJEITADA


def test_decisao_resolvida_nao_resolve_de_novo(gov):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    gov.aprovar(d.id, "t1", "joao")
    with pytest.raises(DecisaoJaResolvida):
        gov.rejeitar(d.id, "t1", "ana")
    with pytest.raises(DecisaoJaResolvida):
        gov.aprovar(d.id, "t1", "ana")


def test_isolamento_entre_tenants(gov):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    with pytest.raises(DecisaoNaoEncontrada):
        gov.obter(d.id, "t2")
    with pytest.raises(DecisaoNaoEncontrada):
        gov.aprovar(d.id, "t2", "joao")
    assert gov.pendentes("t2") == []


def test_adulterar_o_valor_no_banco_invalida_a_assinatura_e_bloqueia_a_aprovacao(gov, tmp_path):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    con = sqlite3.connect(tmp_path / "gov.db")
    con.execute("UPDATE decisoes SET valor = '1.00' WHERE id = ?", (d.id,))
    con.commit()
    con.close()
    assert gov.verificar_assinatura(d.id, "t1") is False
    with pytest.raises(AssinaturaInvalida):
        gov.aprovar(d.id, "t1", "joao")
    eventos = [e["evento"] for e in gov.audit.ler("t1")]
    assert "governanca.assinatura_invalida" in eventos and gov.obter(d.id, "t1").estado == PENDENTE


def test_assinatura_de_outra_chave_nao_vale(gov, tmp_path):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    outro = GovernanceManager(tmp_path / "gov.db", gov.audit, pqc.DilithiumAssinatura.gerar_par(), {"rescisao": Decimal("50000")})
    assert outro.verificar_assinatura(d.id, "t1") is False


def test_cada_passo_vai_para_a_trilha_worm(gov):
    d = gov.registrar("t1", "maria", "rescisao", "80000")
    gov.aprovar(d.id, "t1", "joao")
    eventos = [e["evento"] for e in gov.audit.ler("t1")]
    assert eventos == ["governanca.decisao_registrada", "governanca.decisao_aprovada"] and gov.audit.verificar("t1").ok


def test_valor_invalido_ou_negativo(gov):
    for ruim in ("abc", "-1", None):
        with pytest.raises(GovernancaError):
            gov.registrar("t1", "maria", "rescisao", ruim)


def test_limites_por_json_yaml_e_padrao(tmp_path):
    assert carregar_limites(env={})["rescisao"] == Decimal("50000.00")
    assert carregar_limites('{"rescisao": 1000}')["rescisao"] == Decimal("1000")
    arq = tmp_path / "l.yaml"
    arq.write_text("folha: '5000'\n", encoding="utf-8")
    assert carregar_limites(arq)["folha"] == Decimal("5000")
    assert carregar_limites(env={"GOVERNANCA_LIMITES": '{"ferias": 1}'})["ferias"] == Decimal("1")
    for ruim in ({"rescisao": 0}, {"rescisao": "x"}, {"rescisao": -5}):
        with pytest.raises(GovernancaError):
            carregar_limites(ruim)


def test_par_de_assinatura_em_producao_exige_a_chave_e_em_dev_cria_e_reaproveita(tmp_path, par):
    import base64

    with pytest.raises(GovernancaError):
        carregar_par_de_assinatura({}, tmp_path)
    env = {"GOVERNANCA_DSA_KEY": json.dumps({"pub": base64.b64encode(par.publica).decode(), "priv": base64.b64encode(par.privada).decode()})}
    assert carregar_par_de_assinatura(env).publica == par.publica
    a = carregar_par_de_assinatura({"AGENTE_ENV": "dev"}, tmp_path)
    b = carregar_par_de_assinatura({"AGENTE_ENV": "dev"}, tmp_path)
    assert a.publica == b.publica and (tmp_path / "governanca_dsa.json").exists()


# ------------------------------------------------------------------ redação de logs
def test_filtro_de_redacao_mascara_pii_nas_mensagens_e_nos_argumentos():
    class Coletor(logging.Handler):
        def __init__(self):
            super().__init__()
            self.mensagens = []

        def emit(self, record):
            self.mensagens.append(record.getMessage())

    h = Coletor()
    log = logging.getLogger("teste.redacao")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(h)
    instalar_filtro_de_redacao(log)
    log.info("cliente %s com CPF %s e email %s", "x", "529.982.247-25", "a@b.com")
    log.info("Funcionário: Maria da Silva CNPJ 11.222.333/0001-81")
    texto = " ".join(h.mensagens)
    assert "529.982.247-25" not in texto and "a@b.com" not in texto and "Silva" not in texto and "11.222.333/0001-81" not in texto
    assert "***CPF***" in texto and "***EMAIL***" in texto


def test_filtro_nunca_derruba_o_log():
    f = RedactionFilter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "valor %d", ("texto",), None)  # argumento inválido para %d
    assert f.filter(rec) is True and "suprimida" in rec.msg
