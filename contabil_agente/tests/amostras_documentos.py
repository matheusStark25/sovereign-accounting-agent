"""Amostras sintéticas de documentos (sem dados reais) para os testes da camada de documentos."""

from __future__ import annotations

from typing import Dict, List, Tuple

PESOS_CHAVE = [2, 3, 4, 5, 6, 7, 8, 9]


def dv_chave(base43: str) -> str:
    soma = sum(int(d) * PESOS_CHAVE[i % 8] for i, d in enumerate(reversed(base43)))
    resto = soma % 11
    return str(0 if resto in (0, 1) else 11 - resto)


def sped(registros: List[List[str]]) -> bytes:
    linhas = ["|" + "|".join(r) + "|" for r in registros]
    linhas.append(f"|9999|{len(linhas) + 1}|")
    return ("\r\n".join(linhas) + "\r\n").encode("latin-1")


CNPJ = "11222333000181"
CPF = "52998224725"

CHAVE_BASE = "35" + "2609" + CNPJ + "55" + "001" + "000000123" + "1" + "12345678"
CHAVE = CHAVE_BASE + dv_chave(CHAVE_BASE)


def nfe(vnf: str = "100.00", chave: str = CHAVE, cnpj: str = CNPJ) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><serie>1</serie><nNF>123</nNF><dhEmi>2026-09-10T10:00:00-03:00</dhEmi></ide>
<emit><CNPJ>{cnpj}</CNPJ><xNome>EMPRESA TESTE LTDA</xNome></emit>
<dest><CNPJ>45997418000153</CNPJ></dest>
<total><ICMSTot><vProd>100.00</vProd><vDesc>0.00</vDesc><vST>0.00</vST><vFrete>0.00</vFrete><vSeg>0.00</vSeg><vOutro>0.00</vOutro><vIPI>0.00</vIPI><vNF>{vnf}</vNF></ICMSTot></total>
</infNFe></NFe></nfeProc>""".encode("utf-8")


ESOCIAL_REMUN = f"""<?xml version="1.0" encoding="UTF-8"?>
<eSocial xmlns="http://www.esocial.gov.br/schema/evt/evtRemun/v_S_01_02_00"><evtRemun Id="ID1112223330000002026091000000000001">
<ideEvento><indRetif>1</indRetif><perApur>2026-09</perApur></ideEvento>
<ideEmpregador><tpInsc>1</tpInsc><nrInsc>11222333</nrInsc></ideEmpregador>
<ideTrabalhador><cpfTrab>{CPF}</cpfTrab></ideTrabalhador>
<dmDev><ideDmDev>1</ideDmDev><infoPerApur><ideEstabLot><detVerbas><codRubr>1000</codRubr><vrRubr>3000.00</vrRubr></detVerbas></ideEstabLot></infoPerApur></dmDev>
</evtRemun></eSocial>""".encode("utf-8")

ESOCIAL_DESLIG = f"""<?xml version="1.0" encoding="UTF-8"?>
<eSocial xmlns="http://www.esocial.gov.br/schema/evt/evtDeslig/v_S_01_02_00"><evtDeslig Id="ID1">
<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{CNPJ}</nrInsc></ideEmpregador>
<ideVinculo><cpfTrab>{CPF}</cpfTrab><matricula>1</matricula></ideVinculo>
<infoDeslig><mtvDeslig>02</mtvDeslig><dtDeslig>2026-09-15</dtDeslig></infoDeslig>
</evtDeslig></eSocial>""".encode("utf-8")

REINF = f"""<?xml version="1.0" encoding="UTF-8"?>
<Reinf xmlns="http://www.reinf.esocial.gov.br/schemas/evtServTom/v2_01_02"><evtServTom id="ID1">
<ideEvento><perApur>2026-09</perApur></ideEvento><ideContri><tpInsc>1</tpInsc><nrInsc>11222333</nrInsc></ideContri>
<infoServTom><ideEstabObra><idePrestServ><vlrTotalBruto>1000.00</vlrTotalBruto><vlrTotalRetPrinc>110.00</vlrTotalRetPrinc></idePrestServ></ideEstabObra></infoServTom>
</evtServTom></Reinf>""".encode("utf-8")

HOLERITE = """EMPRESA TESTE LTDA  CNPJ 11.222.333/0001-81
HOLERITE - Competência: 09/2026
Funcionário CPF 529.982.247-25
Salário base 6.000,00
Total de proventos 6.000,00
INSS 641,51
IRRF 385,10
Total de descontos 1.026,61
FGTS 480,00
Líquido a receber 4.973,39
"""

TEXTOS: Dict[str, str] = {
    "HOLERITE": HOLERITE,
    "TRCT": """TERMO DE RESCISÃO DO CONTRATO DE TRABALHO (TRCT)
CNPJ 11.222.333/0001-81  CPF 529.982.247-25
Data de admissão: 10/03/2023   Data de demissão: 15/09/2026
Saldo de salário 1.500,00
Aviso prévio 3.900,00
13º salário 2.500,00
Férias proporcionais 2.000,00
Total bruto 10.566,67
Total de descontos 313,19
Valor líquido 10.253,48
""",
    "RECIBO_FERIAS": """RECIBO DE FÉRIAS
Período aquisitivo 10/03/2025 a 09/03/2026
Início do gozo: 05/10/2026
Valor das férias 3.000,00
1/3 constitucional 1.000,00
Total bruto 4.000,00
INSS 368,60
Líquido a receber 3.631,40
""",
    "CONTRATO_TRABALHO": """CONTRATO INDIVIDUAL DE TRABALHO
EMPREGADOR: EMPRESA TESTE LTDA, CNPJ 11.222.333/0001-81. EMPREGADO: CPF 529.982.247-25.
Cláusula 1ª: admissão em 10/03/2026. Cláusula 2ª: salário mensal de R$ 3.000,00.
Cláusula 3ª: jornada de trabalho de 44 horas semanais.
""",
    "ASO": """ASO - Atestado de Saúde Ocupacional
Exame: admissional. Data do exame: 02/03/2026
Empresa CNPJ 11.222.333/0001-81. Trabalhador CPF 529.982.247-25.
Resultado: apto para a função.
""",
    "DARF": """DARF - Documento de Arrecadação de Receitas Federais
CNPJ 11.222.333/0001-81
Período de apuração: 09/2026
Código da receita 1708
Data de vencimento 20/10/2026
Valor do principal 1.000,00
Valor da multa 20,00
Juros 10,00
Valor total 1.030,00
""",
    "GPS": """GUIA DA PREVIDÊNCIA SOCIAL - GPS
CNPJ 11.222.333/0001-81  Competência 09/2026
Código de pagamento 2100
Valor do INSS 2.000,00
Valor de outras entidades 500,00
ATM 50,00
Total 2.550,00
""",
    "DAS": """Documento de Arrecadação do Simples Nacional - DAS
PGDAS-D  CNPJ 11.222.333/0001-81  Período de apuração: 09/2026
Data de vencimento 20/10/2026
Valor total do documento 1.250,40
""",
    "GFIP": "GFIP/SEFIP - Guia de Recolhimento do FGTS e Informações à Previdência Social\nCNPJ 11.222.333/0001-81 Competência 09/2026\n",
    "GRRF": "GRRF - Guia de Recolhimento Rescisório do FGTS\nCNPJ 11.222.333/0001-81\nValor a recolher 5.052,80\n",
    "FGTS_GUIA": """FGTS Digital - Guia de recolhimento do FGTS
CNPJ 11.222.333/0001-81  Competência 09/2026
Remuneração base 6.000,00
Valor total 480,00
""",
    "FGTS_EXTRATO": """Extrato analítico do FGTS - conta vinculada
PIS 123.45678.91-8
Saldo total 12.000,00
""",
    "DIRF": "DIRF - Declaração do Imposto sobre a Renda Retido na Fonte\nCNPJ 11.222.333/0001-81\nAno-calendário 2024\nBeneficiário CPF 529.982.247-25\n",
    "DCTF": "DCTF - Declaração de Débitos e Créditos Tributários Federais\nCNPJ 11.222.333/0001-81 Competência 09/2026\n",
    "DCTFWEB": "DCTFWeb - declaração de débitos e créditos\nCNPJ 11.222.333/0001-81 Competência 09/2026\n",
    "PER_DCOMP": "PER/DCOMP - Pedido de Restituição ou Declaração de Compensação\nCNPJ 11.222.333/0001-81\nCrédito: pagamento a maior\n",
    "CAGED": "CAGED - Cadastro Geral de Empregados e Desempregados\nCNPJ 11.222.333/0001-81 Competência 09/2026\nAdmissões: 3 Desligamentos: 1\n",
    "RAIS": "RAIS - Relação Anual de Informações Sociais\nCNPJ 11.222.333/0001-81\nAno-calendário 2025\n",
    "INFORME_RENDIMENTOS": """Comprovante de Rendimentos Pagos e de Imposto sobre a Renda Retido na Fonte
Ano-calendário 2025   Fonte pagadora CNPJ 11.222.333/0001-81
Beneficiário CPF 529.982.247-25
Total dos rendimentos 60.000,00
Contribuição previdenciária oficial 7.000,00
Imposto sobre a renda retido na fonte 5.000,00
13º salário 5.000,00
""",
    "NFSE": """NFS-e - Nota Fiscal de Serviços Eletrônica
Prestador CNPJ 11.222.333/0001-81   Tomador CNPJ 45.997.418/0001-53
Valor dos serviços 1.000,00
Valor do ISS 50,00
Competência 09/2026
""",
}

BINARIOS: Dict[str, bytes] = {
    "NFE_XML": nfe(),
    "ESOCIAL_XML": ESOCIAL_REMUN,
    "EFD_REINF": REINF,
    "ECD": sped([["0000", "LECD", "01012026", "31122026", "EMPRESA TESTE LTDA", CNPJ, "SP"], ["I001", "0"]]),
    "ECF": sped([["0000", "LECF", "0001", CNPJ, "EMPRESA TESTE LTDA", "0", "", "", "", "01012026", "31122026", "N", "", "0", "0"], ["0010", "x"]]),
    "EFD_ICMS_IPI": sped([["0000", "017", "0", "01092026", "30092026", "EMPRESA TESTE LTDA", CNPJ, "", "SP", "123456789012"], ["E001", "0"], ["E100", "01092026", "30092026"], ["E110", "0"]]),
    "EFD_CONTRIBUICOES": sped([["0000", "006", "0", "", "", "01092026", "30092026", "EMPRESA TESTE LTDA", CNPJ, "SP"], ["0110", "1"], ["M200", "0"]]),
}


def todas() -> List[Tuple[str, bytes]]:
    amostras = [(codigo, texto.encode("utf-8")) for codigo, texto in TEXTOS.items()]
    amostras += list(BINARIOS.items())
    return amostras
