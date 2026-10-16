"""O PDF precisa ser PDF de verdade, trazer os números do motor e ter campos AcroForm."""

from datetime import date

import pytest
from pypdf import PdfReader
import io

from contabil_agente.calc.servico import calcular
from contabil_agente.documentos import gerar_pdf_calculo, hash_do_resultado

HOJE = date(2026, 9, 20)
RESCISAO = {
    "tipo_rescisao": "sem_justa_causa", "salario": 3000, "data_admissao": "10/03/2023",
    "data_demissao": "15/09/2026", "aviso_previo": "indenizado", "saldo_fgts": 12000,
}


def ler(pdf: bytes):
    return PdfReader(io.BytesIO(pdf))


def texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in ler(pdf).pages)


@pytest.fixture(scope="module")
def pdf_rescisao():
    r = calcular("rescisao", RESCISAO, HOJE)["resultado"]
    return gerar_pdf_calculo("rescisao", r, {"empresa": "Empresa Teste Ltda", "nome_funcionario": "Fulano de Tal", "cpf": "123.456.789-09"}), r


def test_e_um_pdf_valido(pdf_rescisao):
    pdf, _ = pdf_rescisao
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert len(ler(pdf).pages) >= 1


def test_traz_os_numeros_conferidos_a_mao(pdf_rescisao):
    pdf, _ = pdf_rescisao
    t = texto(pdf)
    for esperado in ("10.566,67", "10.253,48", "5.052,80", "632,00"):
        assert esperado in t, esperado
    assert "Fulano de Tal" in t and "Empresa Teste Ltda" in t


def test_tem_campos_acroform_preenchidos_e_editaveis(pdf_rescisao):
    pdf, _ = pdf_rescisao
    campos = ler(pdf).get_fields()
    assert {"total_proventos", "total_descontos", "total_liquido", "assinatura", "nome_conferente"} <= set(campos)
    assert campos["total_liquido"]["/V"] == "R$ 10.253,48"
    assert campos["assinatura"].get("/V") in (None, "")


def test_rodape_tem_o_hash_do_resultado(pdf_rescisao):
    pdf, r = pdf_rescisao
    assert hash_do_resultado(r) in texto(pdf).replace("\n", "")


def test_hash_muda_se_o_resultado_mudar(pdf_rescisao):
    _, r = pdf_rescisao
    adulterado = {**r, "total_liquido": r["total_liquido"] + 0.01}
    assert hash_do_resultado(adulterado) != hash_do_resultado(r)


@pytest.mark.parametrize(
    "tipo,dados",
    [
        ("ferias", {"salario": 3000, "dias_ferias": 30}),
        ("decimo_terceiro", {"salario": 3000, "meses": 8}),
        ("folha", {"salario": 6000}),
        ("inss", {"salario": 5000}),
        ("irrf", {"salario": 6000}),
        ("fgts", {"salario": 3000}),
    ],
)
def test_todos_os_tipos_geram_pdf_com_o_total(tipo, dados):
    r = calcular(tipo, dados, HOJE)["resultado"]
    pdf = gerar_pdf_calculo(tipo, r)
    assert pdf.startswith(b"%PDF-")
    t = texto(pdf)
    principal = r.get("total_liquido") or r.get("inss") or r.get("irrf") or r.get("fgts")
    inteiro, _, dec = f"{principal:,.2f}".partition(".")
    assert inteiro.replace(",", ".") + "," + dec in t


def test_tipo_sem_modelo_e_recusado():
    with pytest.raises(ValueError):
        gerar_pdf_calculo("astrologia", {})


def test_texto_com_caracteres_de_marcacao_nao_quebra():
    r = calcular("rescisao", RESCISAO, HOJE)["resultado"]
    pdf = gerar_pdf_calculo("rescisao", r, {"empresa": "A & B <Ltda>"})
    assert "A & B <Ltda>" in texto(pdf)


def test_campos_do_formulario_ficam_dentro_da_pagina(pdf_rescisao):
    pdf, _ = pdf_rescisao
    leitor = ler(pdf)
    achou = 0
    for pagina in leitor.pages:
        largura, altura = float(pagina.mediabox.width), float(pagina.mediabox.height)
        for anot in pagina.get("/Annots", []):
            x0, y0, x1, y1 = [float(v) for v in anot.get_object()["/Rect"]]
            assert 0 <= x0 < x1 <= largura and 0 <= y0 < y1 <= altura
            achou += 1
    assert achou >= 7
