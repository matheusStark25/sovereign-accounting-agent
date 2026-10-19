"""Diálogo de cálculo: junta os dados ao longo da conversa, pergunta o que falta e calcula.

O estado vive no dicionário da sessão do chat (``estado["calculo"]``). A resposta final
vem do motor ``contabil_agente.calc``: o LLM, quando existe, só reescreve o texto.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from contabil_agente.calc import servico

from . import extracao as ex

_CANCELAR = re.compile(r"\b(cancel|deixa pra la|deixa para la|esquece|esquec|desisti|nao quero mais|parar|para com isso)")
_VERBO_CALCULO = re.compile(r"\b(calcul|quanto|quero|preciso|faz|fazer|simul)")
_NOMES_TIPO = {
    "rescisao": "rescisão",
    "ferias": "férias",
    "decimo_terceiro": "13º salário",
    "inss": "INSS",
    "irrf": "IRRF",
    "fgts": "FGTS mensal",
    "folha": "folha de pagamento",
    "prolabore": "pró-labore",
    "gps": "GPS",
    "das_mei": "DAS do MEI",
    "darf": "DARF em atraso",
}
_EXEMPLOS = {
    "salario": 'Exemplo: "salário de R$ 3.000,00".',
    "tipo_rescisao": "Foi sem justa causa, por justa causa, pedido de demissão ou acordo?",
    "data_admissao": 'Exemplo: "admitido em 10/03/2023".',
    "data_demissao": 'Exemplo: "demitido em 15/09/2026".',
    "aviso_previo": "O aviso prévio foi trabalhado ou indenizado?",
    "aviso_previo_pedido": "O aviso prévio foi trabalhado ou não cumprido?",
    "meses": "Quantos meses (1 a 12)? Exemplo: 8 meses.",
    "prolabore": 'Exemplo: "pró-labore de R$ 5.000,00".',
    "tipo_gps": "É contribuinte individual, facultativo, plano simplificado ou baixa renda?",
    "base": 'Exemplo: "remuneração de R$ 4.000,00".',
    "atividade_mei": "A atividade é comércio, serviços, comércio e serviços ou caminhoneiro?",
    "valor_principal": 'Exemplo: "DARF de R$ 1.000,00".',
    "vencimento": 'Exemplo: "venceu em 20/08/2026".',
    "pagamento": 'Exemplo: "pago em 15/10/2026".',
    "selic_acumulada": 'Exemplo: "SELIC acumulada de 5,2%".',
}


def _guardavel(valor: Any) -> Any:
    return str(valor) if isinstance(valor, Decimal) else valor


class DialogoCalculo:
    def __init__(self, hoje: Optional[date] = None):
        self.hoje = hoje

    # ---------------------------------------------------------------- API
    def processar(self, estado: Dict[str, Any], mensagem: str) -> Optional[Dict[str, Any]]:
        """Devolve a resposta do diálogo, ou ``None`` se a mensagem não é de cálculo."""
        norm = ex.normalizar(mensagem or "")
        ativo = estado.get("calculo")

        if ativo and _CANCELAR.search(norm):
            estado.pop("calculo", None)
            return self._resposta("Tudo bem, cancelei o cálculo. Quando quiser, é só pedir de novo.", "ok")

        extraido = ex.extrair_dados(mensagem)
        tipo_novo = ex.detectar_tipo_calculo(mensagem)
        if ativo is not None and tipo_novo is None and not extraido and ex.pergunta_fora_do_calculo(mensagem):
            return None  # no meio de um cálculo, uma pergunta sobre documento ou regra vai para a assistente; o cálculo espera

        if ativo is None:
            if tipo_novo is None:
                return None
            ativo = estado["calculo"] = {"tipo": tipo_novo, "dados": {}, "ultima_pergunta": None}
        elif tipo_novo and tipo_novo != ativo["tipo"] and _VERBO_CALCULO.search(norm):
            ativo = estado["calculo"] = {"tipo": tipo_novo, "dados": {}, "ultima_pergunta": None}

        dados = ativo["dados"]
        self._mesclar(ativo, dados, extraido, mensagem, norm)

        tipo = ativo["tipo"]
        faltando = servico.campos_faltantes(tipo, dados)
        if faltando:
            return self._perguntar(ativo, faltando)

        # saldo do FGTS: pergunta uma única vez quando a multa depende dele
        if (
            tipo == "rescisao"
            and "saldo_fgts" not in dados
            and not dados.get("recusou_saldo_fgts")
            and str(dados.get("tipo_rescisao")) in ("sem_justa_causa", "acordo")
            and not ativo.get("perguntou_saldo")
        ):
            ativo["perguntou_saldo"] = True
            ativo["ultima_pergunta"] = "saldo_fgts"
            return self._resposta(
                "Tenho tudo para a rescisão, falta só o saldo do FGTS (está no extrato) para calcular a multa. "
                "Me diga o valor, ou responda “sem saldo” que eu calculo e deixo a multa como pendente.",
                "aguardando_dados",
            )

        resultado = servico.calcular(tipo, dados, hoje=self.hoje)
        if resultado["status"] == "faltam_dados":
            return self._perguntar(ativo, resultado["faltando"])
        if resultado["status"] == "erro":
            if resultado.get("codigo") == "dados_invalidos" and "data" in resultado["mensagem"].lower():
                dados.pop("data_admissao", None)
                dados.pop("data_demissao", None)
                ativo["ultima_pergunta"] = "data_admissao"
            if resultado.get("codigo") == "competencia_sem_tabela":
                estado.pop("calculo", None)
            return self._resposta(resultado["mensagem"], "erro_calculo")

        estado.pop("calculo", None)
        estado["ultimo_calculo"] = {"tipo": tipo, "resultado": resultado["resultado"]}
        return self._resposta(resultado["resumo"], "ok", dados_calculados=resultado["resultado"], tipo=tipo)

    # ------------------------------------------------------------- partes
    @staticmethod
    def _resposta(texto: str, status: str, dados_calculados: Optional[dict] = None, tipo: Optional[str] = None) -> Dict[str, Any]:
        return {"resposta": texto, "status": status, "dados_calculados": dados_calculados, "tipo": tipo}

    def _perguntar(self, ativo: Dict[str, Any], faltando: list) -> Dict[str, Any]:
        ativo["ultima_pergunta"] = faltando[0]
        nome = _NOMES_TIPO.get(ativo["tipo"], ativo["tipo"])
        pergunta = servico.pergunta_para(faltando)
        dica = _EXEMPLOS.get(faltando[0], "")
        return self._resposta(f"Certo, vamos calcular {nome}. {pergunta} {dica}".strip(), "aguardando_dados")

    def _mesclar(self, ativo, dados, extraido, mensagem, norm) -> None:
        for chave, valor in extraido.items():
            if chave == "datas_sem_contexto":
                continue
            dados[chave] = _guardavel(valor)

        # datas sem contexto: completa a que falta
        soltas = extraido.get("datas_sem_contexto") or []
        if len(soltas) == 1:
            falta_adm = "data_admissao" not in dados
            falta_dem = "data_demissao" not in dados
            pergunta = ativo.get("ultima_pergunta")
            if falta_adm and not falta_dem:
                dados["data_admissao"] = soltas[0]
            elif falta_dem and not falta_adm:
                dados["data_demissao"] = soltas[0]
            elif falta_adm and falta_dem and pergunta in ("data_admissao", "data_demissao"):
                dados[pergunta] = soltas[0]

        # DARF: data solta responde à data que acabou de ser perguntada
        pergunta_darf = ativo.get("ultima_pergunta")
        if pergunta_darf in ("vencimento", "pagamento") and pergunta_darf not in dados and len(soltas) == 1:
            dados[pergunta_darf] = soltas[0]

        # resposta curta ao que acabou de ser perguntado
        pergunta = ativo.get("ultima_pergunta")
        if pergunta == "atividade_mei" and "atividade_mei" not in dados:
            atividade = ex.extrair_atividade_mei(norm)
            if atividade:
                dados["atividade_mei"] = atividade
        elif pergunta == "tipo_gps" and "tipo_gps" not in dados:
            tipo_gps = ex.extrair_tipo_gps(norm)
            if tipo_gps:
                dados["tipo_gps"] = tipo_gps
        if pergunta in ("prolabore", "base", "valor_principal") and pergunta not in dados:
            v = ex.parse_valor_br(mensagem)
            if v is not None and v > 0 and re.fullmatch(r"[\sr$\d.,kmil]+", norm):
                dados[pergunta] = _guardavel(v)
        elif pergunta == "selic_acumulada" and "selic_acumulada" not in dados:
            m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*", mensagem or "")
            if m:
                dados["selic_acumulada"] = _guardavel(ex.parse_valor_br(m.group(1)))
        if pergunta == "salario" and "salario" not in dados:
            v = ex.parse_valor_br(mensagem)
            if v is not None and v > 0:
                dados["salario"] = _guardavel(v)
        elif pergunta == "meses" and "meses" not in dados:
            m = re.fullmatch(r"\s*(\d{1,2})\s*", mensagem or "")
            if m and 1 <= int(m.group(1)) <= 12:
                dados["meses"] = int(m.group(1))
        elif pergunta == "saldo_fgts" and "saldo_fgts" not in dados:
            v = ex.parse_valor_br(mensagem)
            if v is not None and v >= 0 and re.fullmatch(r"[\sr$\d.,kmil]+", norm):
                dados["saldo_fgts"] = _guardavel(v)
            elif re.search(r"sem saldo|nao sei|nao tenho|depois|pular|ignora", norm):
                dados["recusou_saldo_fgts"] = True
        if pergunta in ("aviso_previo", "aviso_previo_pedido") and "aviso_previo" not in dados:
            if re.fullmatch(r"\s*(indenizado|trabalhado|nao cumprido)\s*", norm):
                dados["aviso_previo"] = norm.strip().replace(" ", "_") if "nao" in norm else norm.strip()
