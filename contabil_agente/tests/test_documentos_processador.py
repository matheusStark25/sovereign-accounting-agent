"""Classificação, extração e conferência dos 27 tipos de documento, e recusa de arquivos perigosos."""

import io

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from contabil_agente.documentos.leitura import ArquivoInvalido, ler_documento
from contabil_agente.documentos.processador import TipoDesconhecido, processar_documento
from contabil_agente.documentos.tipos import TIPOS

from . import amostras_documentos as am


def codigos(r):
    return {a.codigo for a in r.alertas}


def test_ha_pelo_menos_23_tipos():
    assert len(TIPOS) >= 23
    assert {"DIRF", "GFIP", "DCTF", "PER_DCOMP", "ESOCIAL_XML", "EFD_ICMS_IPI", "EFD_CONTRIBUICOES", "ECD", "ECF"} <= set(TIPOS)


def test_toda_amostra_cobre_um_tipo_do_registro():
    assert {c for c, _ in am.todas()} == set(TIPOS)


@pytest.mark.parametrize("codigo,conteudo", am.todas())
def test_classifica_cada_tipo_sozinho(codigo, conteudo):
    r = processar_documento(conteudo)
    assert r.tipo == codigo, (codigo, r.candidatos)
    assert r.confianca >= 0.3
    assert r.extracted_data, f"{codigo}: nada extraído"


@pytest.mark.parametrize("codigo,conteudo", am.todas())
def test_com_o_tipo_informado_extrai_o_mesmo(codigo, conteudo):
    assert processar_documento(conteudo, codigo).tipo == codigo


def test_so_dirf_e_so_das_em_maiuscula_contam_como_sigla():
    # "das" em minúsculas é a preposição, não o DAS do Simples
    r = processar_documento("Obrigações das empresas e das famílias, compromissos das partes.".encode())
    assert r.tipo is None


# ------------------------------------------------------------------------ holerite
def test_holerite_correto_nao_tem_alerta():
    r = processar_documento(am.HOLERITE.encode())
    assert r.extracted_data["competencia"] == "2026-09" and r.extracted_data["liquido"] == "4973.39"
    assert r.calculations["inss_recalculado"] == "641.51"
    assert r.alertas == []


def test_holerite_com_inss_errado_e_liquido_adulterado():
    adulterado = am.HOLERITE.replace("INSS 641,51", "INSS 700,00").replace("4.973,39", "5.973,39")
    r = processar_documento(adulterado.encode())
    assert {"inss_diverge", "liquido_nao_fecha"} <= codigos(r)
    assert r.tem_erro


def test_holerite_com_fgts_errado():
    r = processar_documento(am.HOLERITE.replace("FGTS 480,00", "FGTS 400,00").encode())
    assert "fgts_diverge" in codigos(r)


def test_holerite_de_competencia_sem_tabela_avisa_sem_estimar():
    r = processar_documento(am.HOLERITE.replace("09/2026", "09/2035").encode())
    assert "sem_tabela" in codigos(r) and "inss_recalculado" not in r.calculations


# ------------------------------------------------------------------------- guias
def test_darf_soma_confere_e_adulterada_nao():
    ok = processar_documento(am.TEXTOS["DARF"].encode())
    assert ok.extracted_data["codigo_receita"] == "1708" and ok.alertas == []
    ruim = processar_documento(am.TEXTOS["DARF"].replace("1.030,00", "1.130,00").encode())
    assert "total_nao_fecha" in codigos(ruim)


def test_gps_soma():
    assert processar_documento(am.TEXTOS["GPS"].encode()).alertas == []
    assert "total_nao_fecha" in codigos(processar_documento(am.TEXTOS["GPS"].replace("2.550,00", "2.000,00").encode()))


def test_fgts_guia_confere_8_por_cento():
    assert processar_documento(am.TEXTOS["FGTS_GUIA"].encode()).alertas == []
    assert "fgts_diverge" in codigos(processar_documento(am.TEXTOS["FGTS_GUIA"].replace("480,00", "500,00").encode()))


def test_trct_confere_liquido_e_datas():
    ok = processar_documento(am.TEXTOS["TRCT"].encode())
    assert "liquido_nao_fecha" not in codigos(ok) and ok.extracted_data["data_demissao"] == "2026-09-15"
    assert ok.calculations["liquido_recalculado"] == "10253.48"
    ruim = processar_documento(am.TEXTOS["TRCT"].replace("10.253,48", "9.999,00").encode())
    assert "liquido_nao_fecha" in codigos(ruim)
    invertida = processar_documento(am.TEXTOS["TRCT"].replace("15/09/2026", "15/09/2020").encode())
    assert "datas_invertidas" in codigos(invertida)


def test_dirf_avisa_que_foi_extinta():
    r = processar_documento(am.TEXTOS["DIRF"].encode())
    assert "dirf_extinta" in codigos(r)
    r2 = processar_documento(am.TEXTOS["DIRF"].replace("2024", "2026").encode())
    assert [a for a in r2.alertas if a.codigo == "dirf_extinta"][0].severidade == "aviso"


def test_contrato_confere_minimo_e_jornada():
    ok = processar_documento(am.TEXTOS["CONTRATO_TRABALHO"].encode())
    assert ok.alertas == []
    baixo = processar_documento(am.TEXTOS["CONTRATO_TRABALHO"].replace("3.000,00", "900,00").encode())
    assert "abaixo_do_minimo" in codigos(baixo)
    longa = processar_documento(am.TEXTOS["CONTRATO_TRABALHO"].replace("44 horas", "60 horas").encode())
    assert "jornada_acima_do_limite" in codigos(longa)


def test_informe_de_rendimentos_irrf_maior_que_rendimento():
    r = processar_documento(am.TEXTOS["INFORME_RENDIMENTOS"].replace("5.000,00\n13º", "99.000,00\n13º").encode())
    assert "irrf_maior_que_rendimento" in codigos(r)


def test_fgts_extrato_valida_pis():
    r = processar_documento(am.TEXTOS["FGTS_EXTRATO"].encode())
    assert r.extracted_data["pis"] == "12345678918"
    assert "pis_invalido" in codigos(r)  # DV de 12345678918 está errado: o validador tem que acusar
    certo = processar_documento(am.TEXTOS["FGTS_EXTRATO"].replace("123.45678.91-8", "123.45678.91-9").encode())
    assert "pis_invalido" not in codigos(certo)


# ---------------------------------------------------------------------------- SPED
def test_sped_extrai_periodo_e_cnpj_e_confere_9999():
    r = processar_documento(am.BINARIOS["EFD_ICMS_IPI"])
    assert r.extracted_data["dt_ini"] == "2026-09-01" and r.extracted_data["cnpj"] == "11.222.333/0001-81"
    assert r.alertas == []


def test_sped_com_contagem_errada_ou_sem_9999():
    errado = am.BINARIOS["EFD_ICMS_IPI"].replace(b"|9999|", b"|9999|9")
    assert "estrutura_sped" in codigos(processar_documento(errado, "EFD_ICMS_IPI"))
    sem_fim = b"\r\n".join(am.BINARIOS["EFD_ICMS_IPI"].split(b"\r\n")[:-2]) + b"\r\n"
    assert "estrutura_sped" in codigos(processar_documento(sem_fim, "EFD_ICMS_IPI"))


def test_sped_cnpj_invalido():
    ruim = am.BINARIOS["EFD_CONTRIBUICOES"].replace(b"11222333000181", b"11222333000182")
    assert "cnpj_invalido" in codigos(processar_documento(ruim, "EFD_CONTRIBUICOES"))


def test_apelido_sped_classifica_entre_os_tipos_sped():
    assert processar_documento(am.BINARIOS["ECD"], "SPED").tipo == "ECD"
    assert processar_documento(am.BINARIOS["EFD_CONTRIBUICOES"], "sped").tipo == "EFD_CONTRIBUICOES"


# ----------------------------------------------------------------------------- XML
def test_nfe_valida():
    r = processar_documento(am.nfe())
    assert r.extracted_data["valor_nota"] == "100.00" and r.alertas == []


def test_nfe_com_valor_adulterado_chave_e_cnpj_errados():
    assert "vnf_nao_fecha" in codigos(processar_documento(am.nfe(vnf="150.00")))
    chave_ruim = am.CHAVE[:-1] + str((int(am.CHAVE[-1]) + 1) % 10)
    assert "chave_invalida" in codigos(processar_documento(am.nfe(chave=chave_ruim)))
    assert {"cnpj_invalido", "chave_cnpj_diverge"} <= codigos(processar_documento(am.nfe(cnpj="11222333000182")))


def test_esocial_evento_e_dados():
    r = processar_documento(am.ESOCIAL_REMUN)
    assert r.extracted_data["codigo_evento"] == "S-1200" and r.extracted_data["total_rubricas"] == "3000.00"
    d = processar_documento(am.ESOCIAL_DESLIG)
    assert d.extracted_data["codigo_evento"] == "S-2299" and d.extracted_data["data_desligamento"] == "2026-09-15"


def test_esocial_cpf_invalido():
    ruim = am.ESOCIAL_REMUN.replace(b"52998224725", b"52998224724")
    assert "cpf_invalido" in codigos(processar_documento(ruim))


def test_reinf_valores():
    r = processar_documento(am.REINF)
    assert r.extracted_data["evento"] == "evtServTom" and r.extracted_data["valores"]["vlrTotalBruto"] == "1000.00"


# ------------------------------------------------------------------------- segurança
def test_xml_com_entidade_externa_e_recusado():
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><NFe>&e;</NFe>'
    with pytest.raises(ArquivoInvalido):
        ler_documento(xxe)


def test_xml_bomba_de_entidades_e_recusado():
    bomba = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><l>&c;</l>'
    )
    with pytest.raises(ArquivoInvalido):
        ler_documento(bomba)


def test_arquivo_vazio_pdf_falso_e_caminho_inexistente(tmp_path):
    with pytest.raises(ArquivoInvalido):
        ler_documento(b"   \n ")
    with pytest.raises(ArquivoInvalido):
        ler_documento(b"isto nao e pdf", nome="x.pdf")
    with pytest.raises(ArquivoInvalido):
        ler_documento(str(tmp_path / "nao_existe.pdf"))


def test_arquivo_grande_demais_e_recusado(monkeypatch):
    import contabil_agente.documentos.leitura as leitura

    monkeypatch.setattr(leitura, "TAMANHO_MAXIMO", 10)
    with pytest.raises(ArquivoInvalido):
        ler_documento(b"x" * 11)


def test_tipo_informado_desconhecido():
    with pytest.raises(TipoDesconhecido):
        processar_documento(b"qualquer coisa", "ASTROLOGIA")


def test_tipo_informado_que_o_conteudo_nao_confirma_vira_alerta():
    r = processar_documento(am.TEXTOS["DARF"].encode(), "HOLERITE")
    assert r.tipo == "HOLERITE" and {"tipo_nao_confirmado", "tipo_informado_diverge"} <= codigos(r)


# ---------------------------------------------------------------------------- PDF
def pdf_com_texto(linhas):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for linha in linhas:
        c.drawString(50, y, linha)
        y -= 16
    c.save()
    return buf.getvalue()


def test_pdf_com_texto_e_processado_e_traz_hash_e_paginas():
    pdf = pdf_com_texto(am.HOLERITE.splitlines())
    r = processar_documento(pdf)
    assert r.tipo == "HOLERITE" and r.formato == "pdf" and r.paginas == 1 and len(r.sha256) == 64
    assert r.extracted_data["inss"] == "641.51" and r.alertas == []


def test_pdf_pelo_caminho(tmp_path):
    arq = tmp_path / "holerite.pdf"
    arq.write_bytes(pdf_com_texto(am.HOLERITE.splitlines()))
    assert processar_documento(arq).tipo == "HOLERITE"
    assert processar_documento(str(arq), "HOLERITE").formato == "pdf"


def test_pdf_sem_texto_avisa_que_precisa_de_ocr():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(50, 50, 100, 100)
    c.save()
    r = processar_documento(buf.getvalue())
    assert r.tipo is None and any("OCR" in a for a in r.avisos)


def test_resumo_menciona_erros():
    r = processar_documento(am.HOLERITE.replace("4.973,39", "1,00").encode())
    assert "erro" in r.resumo
