"""Maria Helena com ferramentas: o que o LLM vê (sem CPF/CNPJ em claro), o que as ferramentas recebem (o valor real, só na
requisição) e o que cada ferramenta devolve, sem rede (um LLM roteirizado faz o papel do modelo)."""

import json

from contabil_agente.calc import servico
from contabil_agente.chat import ChatEngine
from contabil_agente.chat.ferramentas import Ferramentas, Pseudonimizador
from contabil_agente.pipeline import ArquivoDestino, DocumentDispatcher, HistoricoDocumentos
from contabil_agente.security.worm_audit import WormAudit

CPF, CNPJ = "529.982.247-25", "11.222.333/0001-81"
HOLERITE = ("HOLERITE - Competência: 09/2026\nSalário base 6.000,00\nTotal de proventos 6.000,00\nINSS 700,00\nIRRF 385,10\n"
            "Total de descontos 1.085,10\nFGTS 480,00\nLíquido a receber 4.914,90\nCNPJ 11.222.333/0001-81\nCPF 529.982.247-25\n")


class LLMRoteirizado:
    """Faz o papel do modelo: em cada rodada chama as ferramentas do roteiro e devolve um texto montado com os resultados."""

    def __init__(self, roteiro, final):
        self.roteiro, self.final, self.vistos, self.resultados = roteiro, final, [], []

    def __call__(self, mensagens):
        self.vistos.append(mensagens)
        return "sem ferramentas"

    def com_ferramentas(self, mensagens, esquemas, executar):
        self.vistos.append(mensagens)
        self.esquemas = esquemas
        chamadas = []
        for nome, argumentos in self.roteiro:
            r = executar(nome, argumentos)
            self.resultados.append(r)
            chamadas.append({"ferramenta": nome, "status": r.get("status")})
        return self.final(self.resultados), chamadas


def _historico_com_holerite(tmp_path, tenant="empresa_a"):
    hist = HistoricoDocumentos(tmp_path / "hist.db")
    disp = DocumentDispatcher(WormAudit(tmp_path / "audit", "a" * 40, fsync=False), hist, destinos=[ArquivoDestino(tmp_path / "arq")])
    r = disp.process(conteudo=HOLERITE.encode(), nome="holerite.txt", tenant=tenant, ator="u", usar_ia=False)
    assert r.estado == "ARCHIVED"
    return hist


# ------------------------------------------------------------------ pseudônimos
def test_cpf_cnpj_e_chave_viram_marcadores_e_voltam_como_a_pessoa_escreveu():
    p = Pseudonimizador()
    texto = p.ocultar(f"CPF {CPF}, de novo 52998224725, CNPJ {CNPJ}, número qualquer 123.456.789-00")
    assert texto == "CPF [CPF_1], de novo [CPF_1], CNPJ [CNPJ_1], número qualquer 123.456.789-00"  # inválido fica como está
    assert p.revelar("o [CPF_1] e o [CNPJ_1]") == f"o {CPF} e o {CNPJ}"
    assert p.revelar_valor({"itens": [{"valor": "[CPF_1]"}]}) == {"itens": [{"valor": CPF}]}
    assert CPF not in json.dumps(p.ocultar_valor({"mascarado": CPF, "lista": [CNPJ]}))


# ------------------------------------------------------------------ cada ferramenta
def test_calcular_usa_o_motor_e_guarda_o_ultimo_calculo():
    f = Ferramentas("t")
    r = f.executar("calcular", {"tipo": "inss", "dados": {"salario": 4500, "competencia": "2026-09"}})
    esperado = servico.calcular("inss", {"salario": 4500, "competencia": "01/09/2026"})  # a ferramenta aceita AAAA-MM e MM/AAAA
    assert r["status"] == "ok" and r["resultado"]["inss"] == esperado["resultado"]["inss"] and f.ultimo_calculo["tipo"] == "inss"
    falta = f.executar("calcular", {"tipo": "rescisao", "dados": {"salario": 3000}})
    assert falta["status"] == "faltam_dados" and "tipo_rescisao" in falta["faltando"]


def test_tabela_vigente_traz_faixas_teto_e_a_norma():
    r = Ferramentas("t").executar("tabela_vigente", {"tributo": "inss", "competencia": "09/2026"})
    assert r["status"] == "ok" and r["teto"] == "8475.55" and "Portaria" in r["norma"] and r["faixas"][0]["aliquota_percentual"] == "7,5"
    irrf = Ferramentas("t").executar("tabela_vigente", {"tributo": "irrf", "competencia": "2026-09"})
    assert irrf["status"] == "ok" and irrf["faixas"] and "deducao_por_dependente" in irrf
    assert Ferramentas("t").executar("tabela_vigente", {"tributo": "iss"})["status"] == "erro"


def test_documentos_recentes_so_da_propria_empresa_e_com_dados_pessoais_mascarados(tmp_path):
    hist = _historico_com_holerite(tmp_path)
    r = Ferramentas("empresa_a", historico=hist).executar("documentos_recentes", {})
    assert r["status"] == "ok" and r["total"] == 1
    doc = r["documentos"][0]
    assert doc["tipo"] == "HOLERITE" and doc["competencia"] and any(a["codigo"] for a in doc["alertas"])  # INSS 700 diverge do recalculado
    assert "52998224725" not in json.dumps(doc) and CPF not in json.dumps(doc)
    assert Ferramentas("empresa_b", historico=hist).executar("documentos_recentes", {})["total"] == 0  # outra empresa não vê


def test_ferramenta_desconhecida_ou_argumento_errado_nao_derruba_a_conversa():
    f = Ferramentas("t")
    assert f.executar("apagar_tudo", {})["status"] == "erro"
    assert f.executar("calcular", {"tipo": "inss", "dados": "salario 3000"})["status"] == "erro"
    assert f.executar("conciliar_fechamento", {"holerites": "x"})["status"] == "erro"


# ------------------------------------------------------------------ a conversa inteira
def test_o_llm_ve_marcadores_a_ferramenta_ve_o_cpf_e_a_resposta_volta_com_o_cpf(tmp_path):
    llm = LLMRoteirizado([("validar_identificadores", {"itens": [{"tipo": "cpf", "valor": "[CPF_1]"}]})],
                         lambda rs: f"O CPF [CPF_1] é {'válido' if rs[0]['todos_validos'] else 'inválido'}.")
    estado = {}
    r = ChatEngine(llm=llm).responder(estado, f"o CPF {CPF} é válido?", ferramentas=Ferramentas("t"))
    enviado_ao_llm = json.dumps(llm.vistos)
    assert "[CPF_1]" in enviado_ao_llm and "52998224725" not in enviado_ao_llm and CPF not in enviado_ao_llm
    resultado = json.dumps(llm.resultados, ensure_ascii=False)
    assert "529.982.247-25" not in resultado and "52998224725" not in resultado  # o resultado da ferramenta não leva o CPF ao LLM
    assert "[CPF_1]" in resultado and "***.982.247-**" not in resultado  # leva o marcador, que o modelo repete e a tela revela
    assert r["resposta"] == f"O CPF {CPF} é válido." and r["ferramentas"] == [{"ferramenta": "validar_identificadores", "status": "ok"}]


def test_calculo_feito_pela_ferramenta_vira_o_cartao_com_pdf_na_tela():
    llm = LLMRoteirizado([("calcular", {"tipo": "prolabore", "dados": {"prolabore": 8000, "competencia": "2026-09"}})],
                         lambda rs: "Calculei o pró-labore.")
    estado = {}
    r = ChatEngine(llm=llm).responder(estado, "me ajuda com o custo de um sócio com pró-labore no simples", ferramentas=Ferramentas("t"))
    assert r["tipo"] == "prolabore" and r["dados_calculados"] and estado["ultimo_calculo"]["tipo"] == "prolabore"
    nomes = [e["function"]["name"] for e in llm.esquemas]
    assert nomes == ["calcular", "tabela_vigente", "validar_identificadores", "documentos_recentes", "conciliar_fechamento", "verificar_conformidade"]


def test_sem_ferramentas_ou_sem_llm_que_as_use_a_conversa_continua_como_antes():
    simples = []
    r = ChatEngine(llm=lambda m: simples.append(m) or "oi").responder({}, "o que é DARF?", ferramentas=Ferramentas("t"))
    assert r["resposta"] == "oi" and "ferramentas" not in r  # LLM sem com_ferramentas: conversa simples
