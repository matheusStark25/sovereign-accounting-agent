from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.security import pqc
from contabil_agente.security.worm_audit import WormAudit
from contabil_agente.tools.base_sovereign import BaseSovereignTool
from contabil_agente.tools.calculo_tool import ToolCalculo


def test_audit_vai_para_a_trilha_worm_sem_criar_arquivos_soltos(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    worm = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    t = BaseSovereignTool(service_name="calculo", worm=worm, tenant="t1")
    t.audit("executado", context={"tipo": "folha"})
    e = worm.ler("t1")[0]
    assert e["evento"] == "calculo.executado" and e["dados"] == {"tipo": "folha"} and worm.verificar("t1").ok
    assert [p.name for p in tmp_path.iterdir()] == ["audit"]  # nada de .sovereign_data nem worm_audit_*.log


def test_proteger_e_abrir_usam_pqc_de_verdade():
    chaves = pqc.gerar_chaves_hibridas()
    t = BaseSovereignTool()
    env = t.proteger(b"dado sensivel", chaves.publica(), aad=b"ctx")
    assert env["alg"] == "ML-KEM-768+X25519" and b"dado sensivel" not in str(env).encode()
    assert t.abrir(env, chaves.privada(), aad=b"ctx") == b"dado sensivel"
    with pytest.raises(pqc.PQCError):
        t.abrir(env, chaves.privada(), aad=b"outro")


def test_nao_ha_atalho_que_devolva_o_texto_sem_cifrar():
    t = BaseSovereignTool()
    with pytest.raises(pqc.PQCError):
        t.proteger(b"x", {"alg": "nenhum"})
    assert not hasattr(t, "zkp_validate_govbr") and not hasattr(t, "crypto_anchor")


def test_valores_legais_vem_das_tabelas_do_motor():
    assert BaseSovereignTool.legal_effective_value("salario_minimo", date(2026, 9, 1)) == Decimal("1621.00")
    assert BaseSovereignTool.legal_effective_value("teto_inss", date(2026, 9, 1)) == Decimal("8475.55")
    assert BaseSovereignTool.legal_effective_value("outra") is None


def test_tool_calculo_herda_a_base_e_audita_na_trilha(tmp_path):
    worm = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    tool = ToolCalculo(hoje=date(2026, 9, 20))
    tool.worm, tool.tenant = worm, "t1"
    assert tool.executar({"salario_bruto": 3000})["status"] == "success"
    assert worm.ler("t1")[-1]["evento"] == "calculadora_trabalhista.calculo_executado"
