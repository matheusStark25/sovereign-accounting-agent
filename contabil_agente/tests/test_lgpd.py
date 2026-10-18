"""LGPD: anonimização (CPF, CNPJ, nome, e-mail), base legal, consentimento, retenção e exclusão."""

import json
import os
import sqlite3
import time

import pytest

from contabil_agente.chat.store import ChatStore
from contabil_agente.lgpd import (
    ConsentimentoStore,
    PIIAnonymizer,
    PoliticaDeRetencao,
    PoliticaInvalida,
    ServicoLGPD,
    TratamentoSemBaseLegal,
    finalidade,
)
from contabil_agente.security.worm_audit import WormAudit

A = PIIAnonymizer.anonymize_text
CPF = "529.982.247-25"
CNPJ = "11.222.333/0001-81"
DIA = 86400


# ---------------------------------------------------------------- anonimização
def test_cpf_cnpj_e_email_somem_com_marcador_do_tipo():
    t = A(f"CPF {CPF} / sem pontos 52998224725 / CNPJ {CNPJ} / contato joao.silva@empresa.com.br")
    assert CPF not in t and "52998224725" not in t and CNPJ not in t and "joao.silva@" not in t
    assert "***CPF***" in t and "***CNPJ***" in t and "***EMAIL***" in t


def test_cnpj_nao_vira_cpf_nem_telefone():
    assert A(f"empresa {CNPJ}") == "empresa ***CNPJ***"


@pytest.mark.parametrize("texto", [
    "Funcionário: Maria da Silva Santos", "Empregado Pedro Álvares", "Nome completo: Ana Souza",
    "Colaborador: JOÃO DE OLIVEIRA", "Beneficiário - Carlos Eduardo Lima", "Sr. Roberto Almeida",
])
def test_nome_depois_de_rotulo_e_mascarado(texto):
    saida = A(texto)
    assert "***NOME***" in saida
    for palavra in ("Silva", "Álvares", "Souza", "OLIVEIRA", "Eduardo", "Almeida"):
        assert palavra not in saida


def test_rotulo_permanece_e_texto_comum_nao_e_mascarado():
    assert A("Funcionário: Maria da Silva").startswith("Funcionário: ")
    assert A("O salário foi pago na sexta e o líquido ficou em R$ 4.973,39") == "O salário foi pago na sexta e o líquido ficou em R$ 4.973,39"
    assert A("calcular rescisão sem justa causa") == "calcular rescisão sem justa causa"


def test_nomes_conhecidos_sao_trocados_onde_aparecerem():
    t = A("Falei com Maria Aparecida ontem; maria aparecida confirmou.", nomes_conhecidos=["Maria Aparecida"])
    assert "Aparecida" not in t and t.count("***NOME***") == 2


def test_sem_marcador_de_tipo():
    assert A(f"CPF {CPF}", preserve_type=False) == "CPF ***"


def test_valores_aninhados_e_idempotencia():
    dado = {"a": f"cpf {CPF}", "b": [f"cnpj {CNPJ}", 3], "c": {"d": "joao@x.com"}}
    r = PIIAnonymizer.anonymize_value(dado)
    assert r == {"a": "cpf ***CPF***", "b": ["cnpj ***CNPJ***", 3], "c": {"d": "***EMAIL***"}}
    assert PIIAnonymizer.anonymize_value(r) == r


def test_hash_exige_chave_e_e_estavel_para_cpf_formatado_ou_nao():
    with pytest.raises(ValueError):
        PIIAnonymizer.hash_pii(CPF, chave=None) if not os.environ.get("PII_HASH_KEY") else (_ for _ in ()).throw(ValueError())
    chave = "k" * 20
    assert PIIAnonymizer.hash_pii(CPF, chave) == PIIAnonymizer.hash_pii("52998224725", chave)
    assert PIIAnonymizer.hash_pii(CPF, chave) != PIIAnonymizer.hash_pii(CPF, "z" * 20)
    assert CPF not in PIIAnonymizer.hash_pii(CPF, chave) and "52998224725" not in PIIAnonymizer.hash_pii(CPF, chave)
    with pytest.raises(ValueError):
        PIIAnonymizer.hash_pii(CPF, "curta")


def test_mask_partial():
    assert PIIAnonymizer.mask_partial("12345678901") == "123******01"
    assert PIIAnonymizer.mask_partial("123") == "***"


# ------------------------------------------------------------------ base legal
def test_finalidade_nao_cadastrada_e_recusada():
    with pytest.raises(TratamentoSemBaseLegal):
        finalidade("vender_dados_para_marketing")


@pytest.fixture()
def lgpd(tmp_path):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    cons = ConsentimentoStore(tmp_path / "lgpd.db", "h" * 20)
    store = ChatStore(str(tmp_path / "chat.db"))
    return ServicoLGPD(audit, cons, raiz_arquivo=tmp_path / "arquivo", chat_store=store)


def test_base_legal_sem_consentimento_para_ia_e_recusada(lgpd):
    assert "art. 7º, V" in lgpd.exigir_base_legal("calculo_trabalhista", "t1")
    assert "art. 7º, II" in lgpd.exigir_base_legal("processamento_de_documentos", "t1")
    with pytest.raises(TratamentoSemBaseLegal, match="consentimento"):
        lgpd.exigir_base_legal("envio_a_provedor_de_ia", "t1")
    assert lgpd.pode_tratar("envio_a_provedor_de_ia", "t1") is False


def test_consentimento_de_sistema_libera_e_revogacao_bloqueia(lgpd):
    lgpd.registrar_consentimento("t1", None, "envio_a_provedor_de_ia", True, "admin")
    assert lgpd.pode_tratar("envio_a_provedor_de_ia", "t1")
    assert not lgpd.pode_tratar("envio_a_provedor_de_ia", "t2")  # outro tenant
    lgpd.registrar_consentimento("t1", None, "envio_a_provedor_de_ia", False, "admin")
    assert not lgpd.pode_tratar("envio_a_provedor_de_ia", "t1")
    assert [h["concedido"] for h in lgpd.consentimentos.historico("t1", None)] == [True, False]


def test_consentimento_por_titular(lgpd):
    lgpd.registrar_consentimento("t1", CPF, "consulta_extrato_fgts", True, "rh")
    assert lgpd.pode_tratar("consulta_extrato_fgts", "t1", CPF)
    assert lgpd.pode_tratar("consulta_extrato_fgts", "t1", "52998224725")  # mesmo CPF sem pontuação
    assert not lgpd.pode_tratar("consulta_extrato_fgts", "t1", "111.444.777-35")


def test_consentimento_nao_guarda_o_cpf_em_claro(lgpd, tmp_path):
    lgpd.registrar_consentimento("t1", CPF, "consulta_extrato_fgts", True, "rh")
    bruto = open(tmp_path / "lgpd.db", "rb").read() + open(tmp_path / "audit" / "t1.worm.jsonl", "rb").read()
    assert b"52998224725" not in bruto and CPF.encode() not in bruto


def test_consentimento_com_finalidade_inexistente_e_recusado(lgpd):
    with pytest.raises(TratamentoSemBaseLegal):
        lgpd.registrar_consentimento("t1", None, "inventada", True, "x")


# ------------------------------------------------------------------- retenção
def test_politica_padrao_e_configuravel_por_dicionario_e_yaml(tmp_path):
    assert PoliticaDeRetencao().prazo("chat") == 90 and PoliticaDeRetencao().prazo("auditoria") is None
    p = PoliticaDeRetencao.carregar({"chat": 30, "documentos": 3650})
    assert p.prazo("chat") == 30 and p.prazo("documentos") == 3650 and p.prazo("temporarios") == 7
    arq = tmp_path / "ret.yaml"
    arq.write_text("chat: 15\nhistorico: 100\n", encoding="utf-8")
    assert PoliticaDeRetencao.carregar(arq).prazo("chat") == 15
    assert PoliticaDeRetencao.carregar(env={"RETENCAO_CONFIG": str(arq)}).prazo("historico") == 100


@pytest.mark.parametrize("ruim", [{"chat": 0}, {"chat": -5}, {"chat": "30"}, {"chat": True}, {"inventada": 10}, {"auditoria": 365}])
def test_politica_invalida_e_recusada(ruim):
    with pytest.raises(PoliticaInvalida):
        PoliticaDeRetencao.carregar(ruim)


def test_executor_apaga_so_o_vencido_e_audita(lgpd, tmp_path):
    pasta = tmp_path / "arquivo" / "t1" / "HOLERITE"
    pasta.mkdir(parents=True)
    velho, novo = pasta / "velho.json", pasta / "novo.json"
    velho.write_text("{}")
    novo.write_text("{}")
    antigo = time.time() - 6 * 365 * DIA
    os.utime(velho, (antigo, antigo))
    sid_velha = lgpd.chat_store.nova_sessao("u", "t1")
    with lgpd.chat_store._db() as con:
        con.execute("UPDATE chat_sessions SET updated_at = ?", (time.time() - 91 * DIA,))
    lgpd.chat_store.nova_sessao("u", "t1")
    r = lgpd.executar_retencao("t1")
    assert r["documentos"] == 1 and r["chat"] == 1 and not velho.exists() and novo.exists()
    assert lgpd.chat_store.carregar(sid_velha, "u", "t1") is None
    assert lgpd.audit.ler("t1")[-1]["evento"] == "lgpd.retencao"


def test_a_auditoria_nunca_e_expurgada(lgpd):
    lgpd.audit.append("x", {}, tenant="t1")
    lgpd.executar_retencao("t1", agora=time.time() + 100 * 365 * DIA)
    assert lgpd.audit.verificar("t1").entradas >= 1


# ------------------------------------------------------------------- exclusão
def preparar_arquivo(lgpd, tmp_path, dias):
    pasta = tmp_path / "arquivo" / "t1" / "HOLERITE"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"doc_{dias}.json"
    arq.write_text(json.dumps({"extracted_data": {"cpf": CPF}}), encoding="utf-8")
    idade = time.time() - dias * DIA
    os.utime(arq, (idade, idade))
    return arq


def test_exclusao_apaga_o_que_ja_passou_do_prazo_e_retem_o_que_a_lei_manda_guardar(lgpd, tmp_path):
    velho = preparar_arquivo(lgpd, tmp_path, 6 * 365)
    recente = preparar_arquivo(lgpd, tmp_path, 30)
    outro = tmp_path / "arquivo" / "t1" / "HOLERITE" / "de_outra_pessoa.json"
    outro.write_text(json.dumps({"cpf": "111.444.777-35"}), encoding="utf-8")
    r = lgpd.excluir_titular("t1", "52998224725", ator="dpo")
    assert not velho.exists() and recente.exists() and outro.exists()
    assert len(r["apagados"]) == 1 and len(r["retidos"]) == 1
    assert "art. 16" in r["retidos"][0]["motivo"] and r["retidos"][0]["apagavel_em_dias"] > 1000


def test_exclusao_edita_conversas_e_apaga_consentimentos(lgpd):
    sid = lgpd.chat_store.nova_sessao("u", "t1")
    lgpd.chat_store.salvar(sid, "u", "t1", {"mensagens": [{"role": "user", "content": f"o CPF {CPF} e {CPF.replace('.', '').replace('-', '')}"}]})
    lgpd.registrar_consentimento("t1", CPF, "consulta_extrato_fgts", True, "rh")
    r = lgpd.excluir_titular("t1", CPF, ator="dpo")
    assert r["conversas_editadas"] == 1 and r["consentimentos"] == 1
    texto = json.dumps(lgpd.chat_store.carregar(sid, "u", "t1"))
    assert CPF not in texto and "DOCUMENTO" in texto
    assert not lgpd.pode_tratar("consulta_extrato_fgts", "t1", CPF)


def test_exclusao_so_mexe_no_tenant_pedido(lgpd, tmp_path):
    outro_tenant = tmp_path / "arquivo" / "t2" / "HOLERITE"
    outro_tenant.mkdir(parents=True)
    arq = outro_tenant / "x.json"
    arq.write_text(CPF)
    antigo = time.time() - 7 * 365 * DIA
    os.utime(arq, (antigo, antigo))
    lgpd.excluir_titular("t1", CPF, ator="dpo")
    assert arq.exists()


def test_exclusao_deixa_na_trilha_so_o_hash_e_os_numeros(lgpd, tmp_path):
    preparar_arquivo(lgpd, tmp_path, 6 * 365)
    lgpd.excluir_titular("t1", CPF, ator="dpo")
    bruto = (tmp_path / "audit" / "t1.worm.jsonl").read_text(encoding="utf-8")
    assert "lgpd.exclusao" in bruto and "52998224725" not in bruto and CPF not in bruto
    assert lgpd.audit.verificar("t1").ok


def test_exclusao_exige_cpf_ou_cnpj_valido_em_tamanho(lgpd):
    for ruim in ("123", "", "abc"):
        with pytest.raises(ValueError):
            lgpd.excluir_titular("t1", ruim, ator="dpo")


def test_exclusao_acha_o_documento_tambem_em_arquivo_original_sem_pontuacao(lgpd, tmp_path):
    pasta = tmp_path / "arquivo" / "t1" / "TRCT"
    pasta.mkdir(parents=True)
    orig = pasta / "abc.txt"
    orig.write_text("TRCT do empregado, CPF 52998224725, demitido em 15/09/2026")
    antigo = time.time() - 6 * 365 * DIA
    os.utime(orig, (antigo, antigo))
    assert lgpd.excluir_titular("t1", CPF, ator="dpo")["apagados"] and not orig.exists()


@pytest.mark.parametrize("ident", [
    "91767398-b00a-4c14-be43-8f63052f2b16",  # os 8 primeiros caracteres são só dígitos: parecem telefone/RG
    "12345678-1234-1234-1234-123456789012",  # UUID só de dígitos
    "a" * 64,
    "0123456789" * 6 + "abcd",  # hash em hexadecimal
])
def test_identificadores_tecnicos_nao_sao_mascarados_como_pii(ident):
    from contabil_agente.lgpd.anonimizacao import PIIAnonymizer

    assert PIIAnonymizer.anonymize_text(ident) == ident
    assert PIIAnonymizer.anonymize_text(f"pedido {ident} do cliente joao@x.com tel 99999-9999") == f"pedido {ident} do cliente ***EMAIL*** tel ***TELEFONE***"


def test_request_id_com_cara_de_telefone_chega_inteiro_na_trilha(tmp_path):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    for rid in ("91767398-b00a-4c14-be43-8f63052f2b16", "12345678-1234-1234-1234-123456789012"):
        audit.append("intelligence.pedido", {"request_id": rid, "entrada": "CPF 529.982.247-25"}, tenant="t")
    dados = [e["dados"] for e in audit.ler("t")]
    assert [d["request_id"] for d in dados] == ["91767398-b00a-4c14-be43-8f63052f2b16", "12345678-1234-1234-1234-123456789012"]
    assert all("52998224725" not in json.dumps(d) and "529.982.247-25" not in json.dumps(d) for d in dados)  # e o CPF segue mascarado
