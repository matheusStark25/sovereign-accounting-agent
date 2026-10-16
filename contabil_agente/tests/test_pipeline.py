"""Pipeline de documentos: 7 estados, agentes, regra de evidência, anomalias, trilha WORM e destinos."""

import hashlib
import hmac
import json
import os
import stat
from datetime import date

import httpx
import pytest

from contabil_agente.documentos.leitura import ArquivoInvalido
from contabil_agente.orchestrator.main import DocumentDispatcher as DispatcherDoReadme
from contabil_agente.pipeline import (
    ArquivoDestino,
    CallbackDestino,
    DeepSeek,
    DocumentDispatcher,
    Estado,
    Gemini,
    HistoricoDocumentos,
    MaquinaDeEstados,
    ProvedorIndisponivel,
    TransicaoInvalida,
    WebhookDestino,
    destinos_do_ambiente,
    provedores_do_ambiente,
)
from contabil_agente.pipeline.agentes import AgenteCorretor, AgenteRevisor, AgenteWorker, Divergencia
from contabil_agente.pipeline.anomalias import z_robusto
from contabil_agente.pipeline.destinos import ErroDeDestino
from contabil_agente.pipeline.evidencia import valor_aparece
from contabil_agente.pipeline.provedores import extrair_json, mascarar
from contabil_agente.resilience import ChamadaResiliente
from contabil_agente.security.worm_audit import WormAudit

from . import amostras_documentos as am

HOJE = date(2026, 10, 15)


class Provedor:
    """LLM falso: responde o que o teste mandar e guarda o que recebeu."""

    def __init__(self, resposta=None, erro=None, nome="falso"):
        self.nome, self.resposta, self.erro, self.chamadas = nome, resposta, erro, []

    def gerar_json(self, sistema, usuario):
        self.chamadas.append((sistema, usuario))
        if self.erro:
            raise self.erro
        return self.resposta(usuario) if callable(self.resposta) else self.resposta


@pytest.fixture()
def audit(tmp_path):
    return WormAudit(tmp_path / "audit", "k" * 40, fsync=False)


@pytest.fixture()
def disp(tmp_path, audit):
    return DocumentDispatcher(
        audit, HistoricoDocumentos(tmp_path / "hist.db"), destinos=[ArquivoDestino(tmp_path / "arquivo")], hoje=HOJE
    )


HOLERITE = am.HOLERITE.encode()


# ----------------------------------------------------------------------- FSM
def test_fsm_caminho_completo():
    m = MaquinaDeEstados()
    for e in (Estado.CLASSIFYING, Estado.PROCESSING, Estado.REVIEWING, Estado.CORRECTING, Estado.REVIEWING, Estado.DISPATCHING, Estado.ARCHIVED):
        m.transitar(e)
    assert m.concluida and m.caminho()[0] == "RECEIVED" and m.caminho()[-1] == "ARCHIVED"


def test_fsm_tem_exatamente_os_7_estados_do_readme():
    assert [e.value for e in Estado] == ["RECEIVED", "CLASSIFYING", "PROCESSING", "REVIEWING", "CORRECTING", "DISPATCHING", "ARCHIVED"]


def test_fsm_pula_correcao_quando_nao_ha_o_que_corrigir():
    m = MaquinaDeEstados()
    for e in (Estado.CLASSIFYING, Estado.PROCESSING, Estado.REVIEWING, Estado.DISPATCHING, Estado.ARCHIVED):
        m.transitar(e)
    assert m.concluida


@pytest.mark.parametrize("de,para", [
    (Estado.RECEIVED, Estado.PROCESSING), (Estado.RECEIVED, Estado.ARCHIVED), (Estado.CLASSIFYING, Estado.REVIEWING),
    (Estado.PROCESSING, Estado.DISPATCHING), (Estado.ARCHIVED, Estado.RECEIVED), (Estado.DISPATCHING, Estado.REVIEWING),
])
def test_fsm_recusa_transicoes_invalidas(de, para):
    m = MaquinaDeEstados(estado=de)
    with pytest.raises(TransicaoInvalida):
        m.transitar(para)


def test_fsm_falha_trava_a_maquina_no_estado_em_que_parou():
    m = MaquinaDeEstados()
    m.transitar(Estado.CLASSIFYING)
    m.falhar("tipo desconhecido")
    assert m.estado is Estado.CLASSIFYING and not m.concluida
    with pytest.raises(TransicaoInvalida):
        m.transitar(Estado.PROCESSING)


# ------------------------------------------------------------------ evidência
@pytest.mark.parametrize("valor,texto", [
    ("6000.00", "Salário 6.000,00"), ("5052.80", "multa R$ 5.052,80"), ("2026-09-15", "demissão em 15/09/2026"),
    ("2026-09", "Competência 09/2026"), ("52998224725", "CPF 529.982.247-25"), ("Fulano", "nome: fulano de tal"),
])
def test_valor_aparece_em_varios_formatos(valor, texto):
    assert valor_aparece(texto, valor)


@pytest.mark.parametrize("valor,texto", [("999.00", "Salário 6.000,00"), ("", "x"), (None, "x"), ("2026-10", "Competência 09/2026")])
def test_valor_que_nao_esta_no_texto_nao_vale(valor, texto):
    assert not valor_aparece(texto, valor)


# ------------------------------------------------------------------ provedores
def transporte(resposta_json, status=200, capturar=None):
    def tratar(request: httpx.Request):
        if capturar is not None:
            capturar.append(request)
        return httpx.Response(status, json=resposta_json)

    return httpx.Client(transport=httpx.MockTransport(tratar))


def resiliencia_rapida(nome):
    return ChamadaResiliente(nome, limite_falhas=2, tentativas=2, timeout=5, excecoes=(httpx.HTTPError, ProvedorIndisponivel), dormir=lambda s: None)


def test_deepseek_formato_da_requisicao_e_mascara_de_pii():
    pegos = []
    cli = transporte({"choices": [{"message": {"content": '{"resumo": "ok"}'}}]}, capturar=pegos)
    p = DeepSeek("chave-secreta", cliente=cli, resiliencia=resiliencia_rapida("ds"))
    assert p.gerar_json("sistema", "CPF 529.982.247-25 CNPJ 11.222.333/0001-81 joao@x.com") == {"resumo": "ok"}
    req = pegos[0]
    assert req.url.path == "/chat/completions" and req.headers["authorization"] == "Bearer chave-secreta"
    corpo = json.loads(req.content)
    enviado = json.dumps(corpo)
    assert corpo["model"] == "deepseek-chat" and "529.982.247-25" not in enviado and "joao@x.com" not in enviado
    assert "***CPF***" in enviado


def test_gemini_formato_da_requisicao():
    pegos = []
    cli = transporte({"candidates": [{"content": {"parts": [{"text": '```json\n{"concorda": true}\n```'}]}}]}, capturar=pegos)
    g = Gemini("chave-g", modelo="gemini-x", cliente=cli, resiliencia=resiliencia_rapida("g"))
    assert g.gerar_json("sis", "texto") == {"concorda": True}
    assert pegos[0].url.path == "/v1beta/models/gemini-x:generateContent" and pegos[0].headers["x-goog-api-key"] == "chave-g"
    assert "key=" not in str(pegos[0].url)  # a chave vai no cabeçalho, não na URL


def test_erro_http_e_resposta_fora_do_formato_viram_provedor_indisponivel():
    for status, corpo in ((500, {}), (200, {"inesperado": 1}), (429, {})):
        p = DeepSeek("k", cliente=transporte(corpo, status), resiliencia=resiliencia_rapida("ds"))
        with pytest.raises(ProvedorIndisponivel):
            p.gerar_json("s", "u")


def test_disjuntor_abre_e_para_de_chamar_o_provedor():
    pegos = []
    p = DeepSeek("k", cliente=transporte({}, 500, pegos), resiliencia=resiliencia_rapida("ds"))
    for _ in range(2):
        with pytest.raises(ProvedorIndisponivel):
            p.gerar_json("s", "u")
    antes = len(pegos)
    with pytest.raises(ProvedorIndisponivel):
        p.gerar_json("s", "u")
    assert len(pegos) == antes


def test_sem_chave_nao_cria_provedor():
    assert provedores_do_ambiente({}) == {"worker": None, "revisor": None}
    com = provedores_do_ambiente({"DEEPSEEK_API_KEY": "a", "GEMINI_API_KEY": "b", "GEMINI_MODEL": "m"})
    assert com["worker"].modelo == "deepseek-chat" and com["revisor"].modelo == "m"
    with pytest.raises(ProvedorIndisponivel):
        DeepSeek("")


def test_extrair_json_tolerante_e_estrito():
    assert extrair_json('texto antes {"a": 1} depois') == {"a": 1}
    assert extrair_json('```json\n{"a": 2}\n```') == {"a": 2}
    for ruim in ("sem json", "[1, 2]", "{quebrado"):
        with pytest.raises(ProvedorIndisponivel):
            extrair_json(ruim)


def test_mascarar_limita_o_tamanho():
    assert len(mascarar("a" * 100000)) <= 24000


# --------------------------------------------------------------------- agentes
def test_worker_deterministico_e_com_llm_e_com_falha():
    assert AgenteWorker(None).processar("t", "HOLERITE", {}, "resumo base").origem == "deterministico"
    llm = Provedor({"resumo": "Resumo da IA.", "campos_adicionais": {"adicional_noturno": "120.00"}})
    s = AgenteWorker(llm, "MARCOS").processar("texto", "HOLERITE", {"a": "1"}, "base")
    assert s.origem == "llm" and s.resumo == "Resumo da IA." and s.sugestoes == {"adicional_noturno": "120.00"}
    assert "MARCOS" in llm.chamadas[0][0]
    s2 = AgenteWorker(Provedor(erro=ProvedorIndisponivel("fora"))).processar("t", "X", {}, "base")
    assert s2.origem == "deterministico" and s2.resumo == "base" and "fora" in s2.erro


def test_revisor_acusa_campo_sem_evidencia_no_texto():
    r = AgenteRevisor(None).revisar("Salário 6.000,00", "HOLERITE", {"salario_base": "6000.00", "inss": "777.00"}, [], "texto")
    assert [d.campo for d in r.divergencias] == ["inss"] and not r.concorda


def test_corretor_so_aceita_valor_proposto_com_evidencia():
    texto = "INSS patronal 1.000,00\nINSS 641,51"
    div = [Divergencia("inss", "pegou o campo errado", "1000.00", "641.51", "llm"), Divergencia("irrf", "x", "9", "123.45", "llm")]
    out = AgenteCorretor().corrigir(texto, {"inss": "1000.00", "irrf": "9"}, div)
    assert out.dados["inss"] == "641.51" and out.dados["irrf"] == "9"
    assert [c.campo for c in out.aplicadas] == ["inss"] and out.rejeitadas[0]["campo"] == "irrf"


def test_corretor_remove_campo_sem_evidencia_e_rejeita_sugestao_inventada():
    out = AgenteCorretor().corrigir(
        "Adicional noturno 120,00", {"fantasma": "42.42"},
        [Divergencia("fantasma", "O valor não aparece no texto do documento.", "42.42")],
        {"adicional_noturno": "120.00", "bonus": "9999.99"},
    )
    assert "fantasma" not in out.dados and out.dados["adicional_noturno"] == "120.00" and "bonus" not in out.dados
    assert any(r["campo"] == "bonus" for r in out.rejeitadas)


# ------------------------------------------------------------ dispatcher: caminho
def test_holerite_percorre_os_estados_e_fica_arquivado(disp, tmp_path):
    r = disp.process(conteudo=HOLERITE, nome="holerite.txt", tenant="empresa_a")
    assert r.estado == "ARCHIVED" and r.falha is None and r.tipo == "HOLERITE"
    assert [e["estado"] for e in r.etapas] == ["RECEIVED", "CLASSIFYING", "PROCESSING", "REVIEWING", "DISPATCHING", "ARCHIVED"]
    assert r.extracted_data["liquido"] == "4973.39" and r.calculations["inss_recalculado"] == "641.51"
    assert r.audit_trail_id.startswith("empresa_a:")
    assert r.agentes == {"worker": "deterministico", "revisor": "deterministico", "corretor": "regras"}


def test_cada_transicao_esta_na_trilha_e_a_cadeia_confere(disp, audit):
    r = disp.process(conteudo=HOLERITE, tenant="empresa_a")
    eventos = [e["evento"] for e in audit.ler("empresa_a")]
    assert eventos == ["documento.received", "documento.classifying", "documento.processing", "documento.reviewing",
                       "documento.dispatching", "documento.archived", "documento.arquivado"]
    assert audit.verificar("empresa_a").ok
    ultimo = audit.ler("empresa_a")[-1]
    assert r.audit_trail_id == f"empresa_a:{ultimo['seq']}:{ultimo['hash'][:16]}"
    trilha = json.dumps(audit.ler("empresa_a"))
    assert "4973.39" not in trilha and "4.973,39" not in trilha  # valores do documento não vão para a trilha


def test_o_exemplo_do_readme_funciona(tmp_path, audit):
    arq = tmp_path / "dirf_2024.txt"
    arq.write_text(am.TEXTOS["DIRF"], encoding="utf-8")
    d = DispatcherDoReadme(audit, destinos=[ArquivoDestino(tmp_path / "a")])
    r = d.process(document_path=str(arq), document_type="DIRF", persona="MARCOS", tenant="t")
    assert r.tipo == "DIRF" and r.extracted_data["ano_calendario"] == "2024"
    assert r.calculations == {} and r.audit_trail_id and r.estado == "ARCHIVED"


def test_arquivamento_grava_original_e_resultado_com_permissao_restrita(disp, tmp_path):
    r = disp.process(conteudo=HOLERITE, nome="holerite.txt", tenant="empresa_a")
    pasta = tmp_path / "arquivo" / "empresa_a" / "HOLERITE"
    json_arq, orig = pasta / f"{r.sha256}.json", pasta / f"{r.sha256}.txt"
    assert orig.read_bytes() == HOLERITE
    assert json.loads(json_arq.read_text(encoding="utf-8"))["extracted_data"]["liquido"] == "4973.39"
    if os.name != "nt":
        assert stat.S_IMODE(json_arq.stat().st_mode) == 0o600


def test_pdf_pelo_pipeline(disp):
    from .test_documentos_processador import pdf_com_texto

    r = disp.process(conteudo=pdf_com_texto(am.HOLERITE.splitlines()), tenant="t")
    assert r.estado == "ARCHIVED" and r.formato == "pdf" and r.alertas == []


# ------------------------------------------------------------ dispatcher: falhas
def test_tipo_nao_identificado_para_em_CLASSIFYING_e_registra_a_falha(disp, audit):
    r = disp.process(conteudo=b"conversa fiada sem nada de contabil", tenant="t")
    assert r.estado == "CLASSIFYING" and r.falha and r.requer_revisao and r.tipo is None
    assert "documento.falha" in [e["evento"] for e in audit.ler("t")] and audit.verificar("t").ok


def test_arquivo_invalido_levanta_e_fica_na_trilha(disp, audit):
    with pytest.raises(ArquivoInvalido):
        disp.process(conteudo=b"   ", tenant="t")
    assert audit.ler("t")[-1]["evento"] == "documento.falha"
    with pytest.raises(ArquivoInvalido):
        disp.process()


def test_tipo_informado_desconhecido_vira_falha_clara(disp):
    r = disp.process(conteudo=HOLERITE, document_type="ASTROLOGIA", tenant="t")
    assert r.estado == "CLASSIFYING" and "desconhecido" in r.falha


def test_falha_ao_arquivar_nao_chega_em_archived(tmp_path, audit):
    class Quebrado(ArquivoDestino):
        def enviar(self, contexto):
            raise ErroDeDestino("disco cheio")

    d = DocumentDispatcher(audit, destinos=[Quebrado(tmp_path)])
    r = d.process(conteudo=HOLERITE, tenant="t")
    assert r.estado == "DISPATCHING" and "arquivar" in r.falha


def test_tenant_invalido_e_recusado_pela_trilha(disp):
    with pytest.raises(ValueError):
        disp.process(conteudo=HOLERITE, tenant="../fora")


# ------------------------------------------------------- dispatcher: com agentes
def test_alucinacao_do_worker_e_rejeitada_e_a_sugestao_valida_e_aceita(tmp_path, audit):
    texto = (am.HOLERITE + "Adicional noturno 120,00\n").encode()
    worker = Provedor({"resumo": "Holerite de setembro.", "campos_adicionais": {"adicional_noturno": "120.00", "bonus_secreto": "9999.99"}})
    d = DocumentDispatcher(audit, worker_llm=worker, destinos=[ArquivoDestino(tmp_path)])
    r = d.process(conteudo=texto, tenant="t")
    assert r.estado == "ARCHIVED" and r.agentes["worker"] == "llm"
    assert r.extracted_data["adicional_noturno"] == "120.00" and "bonus_secreto" not in r.extracted_data
    assert [x["campo"] for x in r.rejeitadas] == ["bonus_secreto"]
    assert [x["etapa"] if "etapa" in x else x["estado"] for x in r.etapas].count("CORRECTING") == 1
    assert "Holerite de setembro" in r.resumo


def test_revisor_llm_corrige_campo_lido_errado_e_os_alertas_somem(tmp_path, audit):
    errado = am.HOLERITE.replace("INSS 641,51", "INSS patronal 1.000,00\nINSS 641,51")
    antes = DocumentDispatcher(audit).process(conteudo=errado.encode(), tenant="a")
    assert antes.extracted_data["inss"] == "1000.00" and "inss_diverge" in {a.codigo for a in antes.alertas}
    revisor = Provedor({"concorda": False, "divergencias": [{"campo": "inss", "valor_proposto": "641.51", "motivo": "pegou o INSS patronal"}]})
    d = DocumentDispatcher(audit, revisor_llm=revisor, destinos=[ArquivoDestino(tmp_path)])
    r = d.process(conteudo=errado.encode(), tenant="b")
    assert r.extracted_data["inss"] == "641.51" and r.agentes["revisor"] == "llm"
    assert r.correcoes[0]["campo"] == "inss" and "inss_diverge" not in {a.codigo for a in r.alertas}
    assert r.divergencias == []


def test_revisor_que_propoe_valor_inventado_nao_muda_nada_e_pede_revisao_humana(tmp_path, audit):
    revisor = Provedor({"divergencias": [{"campo": "inss", "valor_proposto": "1.23", "motivo": "achismo"}]})
    d = DocumentDispatcher(audit, revisor_llm=revisor, destinos=[ArquivoDestino(tmp_path)])
    r = d.process(conteudo=HOLERITE, tenant="t")
    assert r.extracted_data["inss"] == "641.51" and r.estado == "ARCHIVED"
    assert r.rejeitadas and r.requer_revisao and "divergencias_nao_resolvidas" in {a.codigo for a in r.alertas}


def test_llm_fora_do_ar_degrada_para_deterministico_e_avisa(tmp_path, audit):
    fora = Provedor(erro=ProvedorIndisponivel("deepseek: ConnectError"))
    d = DocumentDispatcher(audit, worker_llm=fora, revisor_llm=fora, destinos=[ArquivoDestino(tmp_path)])
    r = d.process(conteudo=HOLERITE, tenant="t")
    assert r.estado == "ARCHIVED" and r.agentes["worker"] == "deterministico" and r.agentes["revisor"] == "deterministico"
    assert sum("modo determinístico" in a for a in r.avisos) == 2


def test_o_texto_enviado_ao_llm_vai_com_pii_mascarado_no_provedor_real(tmp_path, audit):
    pegos = []
    cli = transporte({"choices": [{"message": {"content": '{"resumo": "ok", "campos_adicionais": {}}'}}]}, capturar=pegos)
    worker = DeepSeek("k", cliente=cli, resiliencia=resiliencia_rapida("ds"))
    DocumentDispatcher(audit, worker_llm=worker, destinos=[ArquivoDestino(tmp_path)]).process(conteudo=HOLERITE, tenant="t")
    enviado = pegos[0].content.decode()
    assert "529.982.247-25" not in enviado and "11.222.333/0001-81" not in enviado


def test_llm_pode_classificar_so_com_algum_indicio_no_texto(tmp_path, audit):
    texto = b"Relatorio interno: valores de proventos e descontos do mes, liquido a pagar 100,00"
    ia = Provedor({"tipo": "HOLERITE"})
    r = DocumentDispatcher(audit, worker_llm=ia, destinos=[ArquivoDestino(tmp_path)]).process(conteudo=texto, tenant="t")
    assert r.tipo == "HOLERITE"
    inventado = Provedor({"tipo": "NFE_XML"})
    r2 = DocumentDispatcher(audit, worker_llm=inventado, destinos=[ArquivoDestino(tmp_path)]).process(conteudo=b"texto qualquer sem relacao", tenant="t2")
    assert r2.tipo is None and r2.estado == "CLASSIFYING"


# ----------------------------------------------------------------- anomalias
def test_documento_repetido_e_sinalizado(disp):
    r1 = disp.process(conteudo=HOLERITE, tenant="t")
    r2 = disp.process(conteudo=HOLERITE, tenant="t")
    assert "documento_duplicado" not in {a.codigo for a in r1.alertas}
    dup = [a for a in r2.alertas if a.codigo == "documento_duplicado"]
    assert dup and r1.audit_trail_id in dup[0].mensagem and r2.requer_revisao


def test_mesma_competencia_com_outro_arquivo_vira_aviso(disp):
    disp.process(conteudo=HOLERITE, tenant="t")
    outro = am.HOLERITE.replace("Funcionário CPF 529.982.247-25", "Funcionário CPF 111.444.777-35")
    r = disp.process(conteudo=outro.encode(), tenant="t")
    assert "competencia_repetida" in {a.codigo for a in r.alertas}


def test_historico_e_isolado_por_tenant(disp):
    disp.process(conteudo=HOLERITE, tenant="a")
    assert "documento_duplicado" not in {a.codigo for a in disp.process(conteudo=HOLERITE, tenant="b").alertas}


def test_valor_atipico_pelo_escore_robusto(disp):
    base = am.HOLERITE
    for i, mes in enumerate(("01", "02", "03", "04", "05", "06")):
        v = 6000 + i * 10
        txt = base.replace("09/2026", f"{mes}/2026").replace("6.000,00", f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        disp.process(conteudo=txt.encode(), tenant="t")
    absurdo = base.replace("6.000,00", "60.000,00").replace("09/2026", "07/2026")
    r = disp.process(conteudo=absurdo.encode(), tenant="t")
    assert "valor_atipico" in {a.codigo for a in r.alertas}


def test_z_robusto_precisa_de_historico():
    from decimal import Decimal as D

    assert z_robusto(D("100"), [D("1")] * 4) is None
    assert abs(z_robusto(D("100"), [D(x) for x in (98, 99, 100, 101, 102)])) < 1
    assert z_robusto(D("1000"), [D(x) for x in (98, 99, 100, 101, 102)]) > 3.5


def test_competencia_futura_e_regras_de_impossibilidade(disp):
    futuro = am.HOLERITE.replace("09/2026", "03/2027")
    assert "competencia_futura" in {a.codigo for a in disp.process(conteudo=futuro.encode(), tenant="t").alertas}
    absurdo = am.HOLERITE.replace("INSS 641,51", "INSS 2.500,00").replace("09/2026", "08/2026")
    assert "inss_acima_do_maximo" in {a.codigo for a in disp.process(conteudo=absurdo.encode(), tenant="t").alertas}


# ------------------------------------------------------------------- destinos
def test_webhook_assinado_e_falha_de_webhook_nao_impede_o_arquivamento(tmp_path, audit):
    pegos = []
    cli = httpx.Client(transport=httpx.MockTransport(lambda req: (pegos.append(req), httpx.Response(200))[1]))
    wh = WebhookDestino("https://exemplo.com/hook", "segredo-bem-comprido-123", cliente=cli)
    d = DocumentDispatcher(audit, destinos=[ArquivoDestino(tmp_path), wh])
    r = d.process(conteudo=HOLERITE, tenant="t")
    req = pegos[0]
    assert req.headers["x-signature"] == "sha256=" + hmac.new(b"segredo-bem-comprido-123", req.content, hashlib.sha256).hexdigest()
    assert json.loads(req.content)["sha256"] == r.sha256 and r.estado == "ARCHIVED"

    ruim = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    wh2 = WebhookDestino("https://exemplo.com/hook", "segredo-bem-comprido-123", cliente=ruim,
                         resiliencia=ChamadaResiliente("wh", tentativas=1, timeout=5, excecoes=(httpx.HTTPError,), dormir=lambda s: None))
    r2 = DocumentDispatcher(audit, destinos=[ArquivoDestino(tmp_path), wh2]).process(conteudo=HOLERITE + b"\n", tenant="t")
    assert r2.estado == "ARCHIVED" and "destino_falhou" in {a.codigo for a in r2.alertas}


def test_webhook_exige_https_e_segredo_forte():
    with pytest.raises(ErroDeDestino):
        WebhookDestino("http://exemplo.com/hook", "segredo-bem-comprido-123")
    with pytest.raises(ErroDeDestino):
        WebhookDestino("https://exemplo.com/hook", "curto")


def test_destinos_do_ambiente_liga_o_webhook_so_quando_configurado(tmp_path):
    so_arquivo = destinos_do_ambiente(tmp_path, {})
    assert [d.nome for d in so_arquivo] == ["arquivo"]
    com_webhook = destinos_do_ambiente(tmp_path, {"DOCUMENTOS_WEBHOOK_URL": "https://exemplo.com/hook", "DOCUMENTOS_WEBHOOK_SECRET": "segredo-bem-comprido-123"})
    assert [d.nome for d in com_webhook] == ["arquivo", "webhook"]
    with pytest.raises(ErroDeDestino):  # só a URL, sem segredo: recusa em vez de ignorar em silêncio
        destinos_do_ambiente(tmp_path, {"DOCUMENTOS_WEBHOOK_URL": "https://exemplo.com/hook"})
    with pytest.raises(ErroDeDestino):  # http fora do localhost
        destinos_do_ambiente(tmp_path, {"DOCUMENTOS_WEBHOOK_URL": "http://exemplo.com/hook", "DOCUMENTOS_WEBHOOK_SECRET": "segredo-bem-comprido-123"})


def test_callback_recebe_o_resultado(tmp_path, audit):
    recebidos = []
    d = DocumentDispatcher(audit, destinos=[ArquivoDestino(tmp_path), CallbackDestino(recebidos.append)])
    d.process(conteudo=HOLERITE, tenant="t")
    assert recebidos[0]["tipo"] == "HOLERITE" and recebidos[0]["resultado"]["estado"] == "DISPATCHING"


def test_arquivo_destino_recusa_nome_de_pasta_perigoso(tmp_path):
    dest = ArquivoDestino(tmp_path)
    for tenant in ("../fora", "a/b", ".oculto", "a:b"):
        with pytest.raises(ErroDeDestino):
            dest.enviar({"tenant": tenant, "tipo": "X", "sha256": "ab", "resultado": {}})


def test_do_ambiente_monta_tudo_com_dados_em_disco(tmp_path):
    d = DocumentDispatcher.do_ambiente(tmp_path, env={"AGENTE_ENV": "dev"})
    r = d.process(conteudo=HOLERITE, tenant="t")
    assert r.estado == "ARCHIVED" and (tmp_path / "audit" / "t.worm.jsonl").exists() and (tmp_path / "documentos.db").exists()
    assert d.worker_llm is None and d.revisor_llm is None
