"""Porta de entrada única para quem precisa calcular: chat, API REST, ferramentas e tarefas.

``calcular(tipo, dados)`` nunca estima: se faltar informação devolve
``status = "faltam_dados"`` com a pergunta a fazer; se a legislação carregada não
cobre a data devolve ``status = "erro"`` com a explicação.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .decimo_terceiro import calcular_decimo_terceiro
from .errors import CalculoError, CompetenciaSemTabela, DadosInvalidos
from .ferias import calcular_ferias
from .fgts import calcular_fgts_mensal
from .folha import calcular_folha
from .inss import calcular_inss
from .irrf import calcular_irrf_mensal
from .money import D, q2
from .rescisao import calcular_rescisao, dados_de_dict, ler_data
from .texto import formatar_resultado

TIPOS_CALCULO = ("rescisao", "ferias", "decimo_terceiro", "inss", "irrf", "fgts", "folha")

_ROTULOS = {
    "salario": "o salário base (valor mensal)",
    "tipo_rescisao": "o tipo da rescisão (sem justa causa, justa causa, pedido de demissão ou acordo)",
    "data_admissao": "a data de admissão (DD/MM/AAAA)",
    "data_demissao": "a data de demissão (DD/MM/AAAA)",
    "aviso_previo": "se o aviso prévio foi trabalhado ou indenizado",
    "aviso_previo_pedido": "se o aviso prévio foi trabalhado ou não cumprido",
    "meses": "quantos meses o 13º deve considerar (1 a 12)",
}


def _pegar(dados: Dict[str, Any], *nomes):
    for nome in nomes:
        if dados.get(nome) not in (None, ""):
            return dados[nome]
    return None


def campos_faltantes(tipo: str, dados: Dict[str, Any]) -> List[str]:
    """Campos obrigatórios que ainda não foram informados."""
    faltando: List[str] = []
    if tipo in ("inss", "irrf", "ferias", "decimo_terceiro", "rescisao", "fgts", "folha"):
        if _pegar(dados, "salario_base", "salario") is None:
            faltando.append("salario")
    if tipo == "decimo_terceiro" and _pegar(dados, "meses") is None:
        faltando.append("meses")
    if tipo == "rescisao":
        tipo_resc = str(_pegar(dados, "tipo_rescisao", "tipo") or "").lower()
        if not tipo_resc:
            faltando.append("tipo_rescisao")
        if _pegar(dados, "data_admissao", "admissao") is None:
            faltando.append("data_admissao")
        if _pegar(dados, "data_demissao", "demissao") is None:
            faltando.append("data_demissao")
        if "pedido" in tipo_resc:
            if _pegar(dados, "aviso_previo", "aviso") is None:
                faltando.append("aviso_previo_pedido")
        elif "justa" not in tipo_resc or "sem" in tipo_resc:
            if tipo_resc and _pegar(dados, "aviso_previo", "aviso") is None:
                faltando.append("aviso_previo")
    return faltando


def pergunta_para(faltando: List[str]) -> str:
    itens = [_ROTULOS.get(f, f) for f in faltando]
    if len(itens) == 1:
        return f"Para calcular, preciso de {itens[0]}."
    return "Para calcular, preciso de: " + "; ".join(itens) + "."


def _competencia(dados: Dict[str, Any], hoje: Optional[date]) -> date:
    base = _pegar(dados, "competencia", "data_calculo")
    if base is not None:
        data = ler_data(base, "competência")
    else:
        data = hoje or date.today()
    return date(data.year, data.month, 1)


def calcular(tipo: str, dados: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    """Executa o cálculo ``tipo`` com ``dados``. Sempre devolve um dicionário com ``status``."""
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS_CALCULO:
        return {"status": "erro", "tipo": tipo, "mensagem": f"Cálculo não suportado: {tipo!r}."}

    faltando = campos_faltantes(tipo, dados)
    if faltando:
        return {"status": "faltam_dados", "tipo": tipo, "faltando": faltando, "pergunta": pergunta_para(faltando)}

    try:
        competencia = _competencia(dados, hoje)
        salario = _pegar(dados, "salario_base", "salario")
        dependentes = int(_pegar(dados, "dependentes_irrf", "dependentes") or 0)
        adicionais = _pegar(dados, "adicionais_mensais", "adicionais") or 0
        variaveis = _pegar(dados, "media_variaveis") or 0

        if tipo == "inss":
            r = calcular_inss(salario, competencia)
            resultado = {
                "status": "success",
                "base": float(q2(r.base)),
                "base_limitada_ao_teto": float(q2(r.base_limitada_ao_teto)),
                "inss": float(r.valor),
                "faixas": [
                    {"de": float(p.de), "ate": float(p.ate), "aliquota": float(p.aliquota),
                     "base_na_faixa": float(q2(p.base_na_faixa)), "valor": float(q2(p.valor))}
                    for p in r.partes
                ],
                "tabela": f"{r.norma} [{r.verificacao}]",
                "competencia": f"{competencia:%Y-%m}",
            }
        elif tipo == "irrf":
            inss = D(_pegar(dados, "inss") if _pegar(dados, "inss") is not None else calcular_inss(salario, competencia).valor, "INSS")
            r = calcular_irrf_mensal(salario, competencia, inss=inss, dependentes=dependentes,
                                     pensao_alimenticia=_pegar(dados, "pensao_alimenticia") or 0)
            resultado = {
                "status": "success",
                "rendimentos_tributaveis": float(q2(r.rendimentos_tributaveis)),
                "inss_considerado": float(q2(inss)),
                "opcao_deducao": r.opcao_deducao,
                "base_calculo": float(q2(r.base_calculo)),
                "imposto_tabela": float(q2(r.imposto_tabela)),
                "reducao": float(q2(r.reducao)),
                "irrf": float(r.valor),
                "tabela": f"{r.norma} [{r.verificacao}]",
                "competencia": f"{competencia:%Y-%m}",
            }
        elif tipo == "ferias":
            r = calcular_ferias(
                salario, competencia,
                dias_gozados=int(_pegar(dados, "dias_ferias", "dias_gozados") or 30),
                dias_vendidos=int(_pegar(dados, "dias_vendidos", "abono_dias") or 0),
                adicionais_mensais=adicionais, media_variaveis=variaveis, dependentes=dependentes,
            )
            resultado = r.to_dict()
        elif tipo == "decimo_terceiro":
            r = calcular_decimo_terceiro(
                salario, int(_pegar(dados, "meses")), competencia,
                adicionais_mensais=adicionais, media_variaveis=variaveis, dependentes=dependentes,
                adiantamento=_pegar(dados, "adiantamento_13"),
            )
            resultado = r.to_dict()
        elif tipo == "fgts":
            resultado = calcular_fgts_mensal(salario, _pegar(dados, "categoria") or "empregado").to_dict()
        elif tipo == "folha":
            resultado = calcular_folha(
                salario, competencia,
                adicionais_mensais=adicionais,
                horas_extras=_pegar(dados, "horas_extras") or 0,
                dsr_horas_extras=_pegar(dados, "dsr_horas_extras") or 0,
                outros_proventos=_pegar(dados, "outros_proventos") or 0,
                dependentes=dependentes,
                pensao_alimenticia=_pegar(dados, "pensao_alimenticia") or 0,
                custo_vale_transporte=_pegar(dados, "custo_vale_transporte") or 0,
                outros_descontos=_pegar(dados, "outros_descontos") or 0,
                categoria_fgts=_pegar(dados, "categoria") or "empregado",
            ).to_dict()
        else:  # rescisao
            resultado = calcular_rescisao(dados_de_dict(dados)).to_dict()
    except CompetenciaSemTabela as exc:
        return {"status": "erro", "tipo": tipo, "codigo": "competencia_sem_tabela", "mensagem": str(exc)}
    except DadosInvalidos as exc:
        return {"status": "erro", "tipo": tipo, "codigo": "dados_invalidos", "mensagem": str(exc)}
    except CalculoError as exc:
        return {"status": "erro", "tipo": tipo, "codigo": "calculo", "mensagem": str(exc)}

    return {
        "status": "ok",
        "tipo": tipo,
        "resultado": resultado,
        "resumo": formatar_resultado(tipo, resultado),
        "pendencias": resultado.get("pendencias", []),
    }
