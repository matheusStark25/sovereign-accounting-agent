import pytest

from contabil_agente.documentos import validadores as v


@pytest.mark.parametrize("cpf", ["529.982.247-25", "52998224725", "111.444.777-35"])
def test_cpf_valido(cpf):
    assert v.validar_cpf(cpf)


@pytest.mark.parametrize("cpf", ["529.982.247-24", "111.111.111-11", "123", "", None, "000.000.000-00", "abcdefghijk"])
def test_cpf_invalido(cpf):
    assert not v.validar_cpf(cpf)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-81", "11222333000181", "45.997.418/0001-53"])
def test_cnpj_valido(cnpj):
    assert v.validar_cnpj(cnpj)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-82", "00000000000000", "123", "", None])
def test_cnpj_invalido(cnpj):
    assert not v.validar_cnpj(cnpj)


def test_pis_valido_e_invalido():
    # 1234567891 + DV: pesos 3,2,9,8,7,6,5,4,3,2 -> soma 168, resto 3, DV 11 - 3 = 8... conferido abaixo
    soma = sum(int(d) * p for d, p in zip("1234567891", [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    assert v.validar_pis(f"1234567891{dv}")
    assert v.validar_pis(f"123.45678.91-{dv}")
    assert not v.validar_pis(f"1234567891{(dv + 1) % 10}")
    assert not v.validar_pis("12345678918")
    assert not v.validar_pis("11111111111")


def test_chave_de_acesso_nfe():
    base = "3519" + "09" + "11222333000181" + "55" + "001" + "000000123" + "1" + "12345678"  # 43 dígitos
    assert len(base) == 43
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(base)))
    resto = soma % 11
    dv = 0 if resto in (0, 1) else 11 - resto
    chave = base + str(dv)
    assert v.validar_chave_acesso(chave)
    errada = base + str((dv + 1) % 10)
    assert not v.validar_chave_acesso(errada)
    assert not v.validar_chave_acesso(chave[:-1])


def test_formatacao_e_mascara():
    assert v.formatar_cpf("52998224725") == "529.982.247-25"
    assert v.formatar_cnpj("11222333000181") == "11.222.333/0001-81"
    assert v.formatar_cpf("123") is None
    assert v.mascarar_cpf("529.982.247-25") == "***.982.247-**"
    assert "529" not in v.mascarar_cpf("52998224725")
    assert v.mascarar_cnpj("11222333000181").startswith("**.222.333/")
