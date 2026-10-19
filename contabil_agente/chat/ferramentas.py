"""Ferramentas da Maria Helena: o que ela consulta e faz de verdade no sistema durante a conversa.

O LLM escolhe a ferramenta e os argumentos; quem calcula, valida, confere e lê documentos é o código do sistema (motor de
cálculo, agentes, histórico de documentos da empresa). Nada de conta "de cabeça".

Privacidade: CPF, CNPJ, PIS e chave de acesso que aparecem na conversa viram marcadores (``[CPF_1]``) antes de ir ao provedor
de IA. Se o LLM usar um marcador num argumento, a ferramenta recebe o valor real, só dentro desta requisição; o que a
ferramenta devolve passa de novo pelos marcadores e pelo mascaramento antes de voltar ao LLM. O mapa de marcadores nunca é
guardado.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from contabil_agente.calc import servico
from contabil_agente.calc.tables import tabela_inss, tabela_irrf
from contabil_agente.documentos.validadores import so_digitos, validar_chave_acesso, validar_cnpj, validar_cpf, validar_pis
from contabil_agente.lgpd.anonimizacao import PIIAnonymizer

logger = logging.getLogger(__name__)

# do mais longo para o mais curto: uma chave de acesso contém um CNPJ, que não pode ser trocado antes
_PADROES = (
    ("CHAVE", re.compile(r"(?<!\d)(?:\d{4}[ .]?){10}\d{4}(?!\d)"), validar_chave_acesso),
    ("CNPJ", re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"), validar_cnpj),
    ("CPF", re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)"), validar_cpf),
    ("PIS", re.compile(r"(?<!\d)\d{3}\.?\d{5}\.?\d{2}-?\d(?!\d)"), validar_pis),
)
class ErroDeFerramenta(ValueError):
    """Argumento que a ferramenta não aceita: volta ao LLM como ``status: erro`` com a mensagem."""


_MARCADOR = re.compile(r"\[(CHAVE|CNPJ|CPF|PIS)_(\d+)\]")


class Pseudonimizador:
    """Troca identificadores válidos por marcadores estáveis dentro de uma requisição (e desfaz quando precisa)."""

    def __init__(self) -> None:
        self._por_valor: Dict[str, str] = {}
        self._por_marcador: Dict[str, str] = {}

    def ocultar(self, texto: str) -> str:
        for rotulo, padrao, valido in _PADROES:
            def trocar(m: "re.Match[str]") -> str:
                digitos = so_digitos(m.group(0))
                if not valido(digitos):
                    return m.group(0)
                if digitos not in self._por_valor:
                    marcador = f"[{rotulo}_{sum(1 for k in self._por_marcador if k.startswith('[' + rotulo)) + 1}]"
                    self._por_valor[digitos], self._por_marcador[marcador] = marcador, m.group(0)  # volta como a pessoa escreveu
                return self._por_valor[digitos]

            texto = padrao.sub(trocar, texto)
        return texto

    def revelar(self, texto: str) -> str:
        return _MARCADOR.sub(lambda m: self._por_marcador.get(m.group(0), m.group(0)), texto)

    def revelar_valor(self, valor: Any) -> Any:
        if isinstance(valor, str):
            return self.revelar(valor)
        if isinstance(valor, dict):
            return {k: self.revelar_valor(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [self.revelar_valor(v) for v in valor]
        return valor

    def ocultar_valor(self, valor: Any) -> Any:
        if isinstance(valor, str):
            return PIIAnonymizer.anonymize_text(self.ocultar(valor))
        if isinstance(valor, dict):
            return {k: self.ocultar_valor(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [self.ocultar_valor(v) for v in valor]
        return valor


def _pct(aliquota: Any) -> str:
    return f"{aliquota * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _tabela(tributo: str, competencia: Optional[str], hoje: Optional[date]) -> Dict[str, Any]:
    quando = hoje or date.today()
    if competencia:
        m = re.fullmatch(r"(\d{4})-(\d{2})", competencia.strip()) or re.fullmatch(r"(\d{2})/(\d{4})", competencia.strip())
        if not m:
            raise ErroDeFerramenta("Competência no formato AAAA-MM ou MM/AAAA.")
        ano, mes = (int(m.group(1)), int(m.group(2))) if len(m.group(1)) == 4 else (int(m.group(2)), int(m.group(1)))
        quando = date(ano, mes, 1)
    if tributo == "inss":
        t = tabela_inss(quando)
        return {"tributo": "INSS (empregado)", "vigencia": f"{t.vigencia_inicio:%d/%m/%Y} a {t.vigencia_fim:%d/%m/%Y}" if t.vigencia_fim else f"desde {t.vigencia_inicio:%d/%m/%Y}",
                "norma": t.norma, "verificacao": t.verificacao, "salario_minimo": str(t.salario_minimo), "teto": str(t.teto),
                "faixas": [{"ate": str(f.ate), "aliquota_percentual": _pct(f.aliquota)} for f in t.faixas]}
    if tributo == "irrf":
        t = tabela_irrf(quando)
        saida = {"tributo": "IRRF (mensal)", "vigencia": f"desde {t.vigencia_inicio:%d/%m/%Y}", "norma": t.norma, "verificacao": t.verificacao,
                 "faixas": [{"ate": str(f.ate) if f.ate is not None else "acima", "aliquota_percentual": _pct(f.aliquota), "deducao": str(f.deducao)}
                            for f in t.faixas],
                 "deducao_por_dependente": str(t.deducao_dependente), "desconto_simplificado": str(t.desconto_simplificado)}
        if t.reducao:
            saida["reducao"] = {"norma": t.reducao.norma, "isento_ate": str(t.reducao.ate), "reducao_parcial_ate": str(t.reducao.parcial_ate)}
        return saida
    raise ErroDeFerramenta("Tributo: inss ou irrf.")


class Ferramentas:
    """As ferramentas de uma empresa (tenant). Cada chamada devolve um dicionário com ``status``."""

    def __init__(self, tenant: str, historico: Any = None, lgpd: Any = None, hoje: Optional[date] = None):
        self.tenant, self._historico, self._hoje = tenant, historico, hoje
        # importado aqui: os agentes usam a LGPD, que usa o chat (importar no topo do módulo fecharia um ciclo)
        from contabil_agente.agentes import ComplianceAgent, ReconciliationAgent, TaxAgent, ValidationAgent

        self._tax, self._val, self._conc = TaxAgent(hoje), ValidationAgent(), ReconciliationAgent()
        self._conf = ComplianceAgent(lgpd, tenant)
        self.ultimo_calculo: Optional[Dict[str, Any]] = None  # o último cálculo que deu certo (a tela mostra o cartão e o PDF)
        self._funcoes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "calcular": self._calcular,
            "tabela_vigente": lambda a: {"status": "ok", **_tabela(str(a.get("tributo", "")).lower(), a.get("competencia"), self._hoje)},
            "validar_identificadores": self._validar,
            "documentos_recentes": self._documentos,
            "conciliar_fechamento": lambda a: self._conc.executar("fechamento", a),
            "verificar_conformidade": lambda a: self._conf.executar("verificar", {"dados": a.get("dados", {})}),
        }

    # ------------------------------------------------------------------ esquemas (formato de ferramentas da API da Groq/OpenAI)
    @property
    def esquemas(self) -> List[Dict[str, Any]]:
        def f(nome: str, descricao: str, propriedades: Dict[str, Any], obrigatorios: List[str]) -> Dict[str, Any]:
            return {"type": "function", "function": {"name": nome, "description": descricao,
                                                     "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios}}}

        return [
            f("calcular",
              "Faz um cálculo trabalhista ou tributário com o motor do sistema (aritmética decimal, tabelas oficiais). Use SEMPRE que a "
              "resposta envolver valor em reais. Campos por tipo: rescisao (salario, tipo_rescisao: sem justa causa|justa causa|pedido de "
              "demissão|acordo, data_admissao e data_demissao DD/MM/AAAA, aviso_previo: trabalhado|indenizado, saldo_fgts opcional); "
              "ferias (salario, dias_ferias, dias_vendidos opcional); decimo_terceiro (salario, meses 1-12); inss, irrf, fgts (salario, "
              "dependentes opcional); folha (salario, horas_extras, dependentes, outros_descontos opcionais); prolabore (prolabore); gps "
              "(tipo_gps: contribuinte_individual|facultativo|plano_simplificado|baixa_renda, base); das_mei (atividade_mei: "
              "comercio|servicos|comercio_e_servicos|caminhoneiro); darf (valor_principal, vencimento, pagamento DD/MM/AAAA, "
              "selic_acumulada em %). competencia (MM/AAAA) opcional. Valores como número (3000.50). Se faltar dado, a ferramenta diz o que perguntar.",
              {"tipo": {"type": "string", "enum": list(servico.TIPOS_CALCULO)}, "dados": {"type": "object"}}, ["tipo", "dados"]),
            f("tabela_vigente", "Faixas, alíquotas, teto e a norma da tabela de INSS ou IRRF vigente numa competência (a do sistema).",
              {"tributo": {"type": "string", "enum": ["inss", "irrf"]}, "competencia": {"type": "string", "description": "AAAA-MM; padrão: hoje"}},
              ["tributo"]),
            f("validar_identificadores", "Valida CPF, CNPJ, PIS ou chave de acesso pelo dígito verificador. Pode receber marcadores como [CPF_1].",
              {"itens": {"type": "array", "items": {"type": "object", "properties": {
                  "tipo": {"type": "string", "enum": ["cpf", "cnpj", "pis", "chave_nfe"]}, "valor": {"type": "string"}}, "required": ["tipo", "valor"]}}},
              ["itens"]),
            f("documentos_recentes",
              "Os últimos documentos que a empresa enviou ao sistema (holerites, guias, extratos, NF-e...), com tipo, competência, "
              "alertas da conferência e os dados extraídos. Use quando perguntarem sobre 'o documento', 'a guia', 'o que eu mandei'.",
              {"limite": {"type": "integer", "minimum": 1, "maximum": 20}, "tipo": {"type": "string", "description": "filtra pelo tipo, ex.: HOLERITE, GUIA_FGTS, DAS"}},
              []),
            f("conciliar_fechamento",
              "Concilia holerites com a guia do FGTS, a GPS e o DARF do IRRF e aponta a diferença em reais. holerites: lista com "
              "total_proventos, inss, irrf; guia_fgts: {valor_fgts}; gps: {total}; darf: {valor_principal, codigo_receita}.",
              {"holerites": {"type": "array", "items": {"type": "object"}}, "guia_fgts": {"type": "object"}, "gps": {"type": "object"},
               "darf": {"type": "object"}}, ["holerites"]),
            f("verificar_conformidade", "Confere dados de um pagamento contra as regras de conformidade (salário mínimo, CPF, competência...).",
              {"dados": {"type": "object"}}, ["dados"]),
        ]

    # ------------------------------------------------------------------ execução
    def executar(self, nome: str, argumentos: Dict[str, Any]) -> Dict[str, Any]:
        funcao = self._funcoes.get(nome)
        if funcao is None:
            return {"status": "erro", "mensagem": f"Ferramenta desconhecida: {nome}."}
        if not isinstance(argumentos, dict):
            return {"status": "erro", "mensagem": "Argumentos precisam ser um objeto JSON."}
        try:
            return funcao(argumentos)
        except ErroDeFerramenta as exc:
            return {"status": "erro", "mensagem": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a conversa segue; o LLM recebe o motivo genérico
            logger.warning("Ferramenta %s falhou: %s", nome, type(exc).__name__)
            return {"status": "erro", "mensagem": f"A ferramenta {nome} falhou ({type(exc).__name__})."}

    def _calcular(self, a: Dict[str, Any]) -> Dict[str, Any]:
        tipo, dados = str(a.get("tipo", "")), a.get("dados") or {}
        if not isinstance(dados, dict):
            raise ErroDeFerramenta("dados precisa ser um objeto.")
        dados = dict(dados)
        for campo in ("competencia", "data_calculo"):  # o motor quer DD/MM/AAAA; o modelo costuma mandar AAAA-MM ou MM/AAAA
            valor = str(dados.get(campo) or "").strip()
            m = re.fullmatch(r"(\d{4})-(\d{1,2})", valor) or re.fullmatch(r"(\d{1,2})/(\d{4})", valor)
            if m:
                ano, mes = (m.group(1), m.group(2)) if len(m.group(1)) == 4 else (m.group(2), m.group(1))
                dados[campo] = f"01/{int(mes):02d}/{ano}"
        r = servico.calcular(tipo, dados, hoje=self._hoje)
        if r.get("status") == "ok":
            self.ultimo_calculo = {"tipo": tipo, "resultado": r.get("resultado"), "resumo": r.get("resumo")}
        return r

    def _validar(self, a: Dict[str, Any]) -> Dict[str, Any]:
        itens = a.get("itens", [])
        r = self._val.executar("identificadores", {"itens": itens})
        # devolve o identificador como veio (o motor da conversa o troca pelo marcador [CPF_1] antes de ir ao LLM); a versão
        # mascarada (***.982.247-**) fazia o modelo repetir a máscara na resposta em vez do marcador
        for item, entrada in zip(r.get("itens", []), itens if isinstance(itens, list) else []):
            if isinstance(entrada, dict):
                item.pop("mascarado", None)
                item["identificador"] = str(entrada.get("valor", ""))
        return r

    def _documentos(self, a: Dict[str, Any]) -> Dict[str, Any]:
        if self._historico is None:
            return {"status": "ok", "documentos": [], "observacao": "histórico de documentos indisponível"}
        tipo = str(a.get("tipo") or "").upper()
        docs = self._historico.recentes(self.tenant, int(a.get("limite") or 10) if not tipo else 50)
        if tipo:
            docs = [d for d in docs if d.get("tipo") == tipo][: int(a.get("limite") or 10)]
        return {"status": "ok", "documentos": docs, "total": len(docs)}

    @staticmethod
    def resumo_json(valor: Any, limite: int = 12000) -> str:
        """O que volta ao LLM: JSON compacto e limitado (respostas enormes não ajudam e custam caro)."""
        texto = json.dumps(valor, ensure_ascii=False, default=str, separators=(",", ":"))
        return texto if len(texto) <= limite else texto[:limite] + "…(cortado)"
