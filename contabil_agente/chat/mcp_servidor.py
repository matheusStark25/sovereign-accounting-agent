"""Servidor MCP (Model Context Protocol) com as ferramentas da Maria Helena.

Um assistente de IA compatível com MCP (Claude Desktop, Claude Code, Cursor...) passa a usar as mesmas ferramentas do
chat: o modelo escolhe a ferramenta e preenche os argumentos; quem calcula, valida e confere é o código do sistema.

    python -m agente_v2.cli servidor-mcp

Transporte: stdio, uma mensagem JSON-RPC 2.0 por linha, em UTF-8 (o padrão do MCP para servidor local). O protocolo que
um servidor de ferramentas precisa é pequeno (initialize, ping, tools/list e tools/call) e está todo aqui, sem SDK: assim a
imagem Docker e as dependências que o CI audita não mudam.

As mesmas proteções do chat valem aqui:
- o resultado de cada ferramenta passa por ``blindar``: texto com cara de instrução escondida vira aviso;
- CPF, CNPJ, PIS e chave de acesso no resultado viram marcadores (``[CPF_1]``) e o resto passa pelo mascaramento da LGPD:
  o servidor não devolve identificador pessoal ao modelo;
- nada fica gravado: cada chamada é independente, sem banco e sem histórico.

``documentos_recentes`` fica de fora: depende do histórico de documentos de uma empresa, que só existe na API com login.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from typing import Any, Dict, Optional, TextIO

from contabil_agente.chat.ferramentas import Ferramentas, Pseudonimizador
from contabil_agente.security.injecao import AVISO_FERRAMENTA, blindar

logger = logging.getLogger(__name__)

VERSOES_DO_PROTOCOLO = ("2025-06-18", "2025-03-26", "2024-11-05")  # a primeira é a preferida
SERVIDOR = {"name": "sovereign-accounting-agent", "title": "Sovereign Accounting Agent", "version": "1.0.0"}
FERRAMENTAS_EXPOSTAS = ("calcular", "tabela_vigente", "validar_identificadores", "conciliar_fechamento", "verificar_conformidade")
INSTRUCOES = (
    "Ferramentas de Departamento Pessoal e contabilidade do Brasil. Todo valor em reais vem do motor de cálculo do sistema, "
    "com as tabelas oficiais da competência: use os números do resultado, sem refazer a conta. Se faltar dado, o resultado "
    "diz o que perguntar."
)

# códigos de erro do JSON-RPC 2.0
ERRO_DE_LEITURA, PEDIDO_INVALIDO, METODO_INEXISTENTE, PARAMETROS_INVALIDOS, ERRO_INTERNO = -32700, -32600, -32601, -32602, -32603


def _resposta(ident: Any, resultado: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": resultado}


def _erro(ident: Any, codigo: int, mensagem: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": codigo, "message": mensagem}}


def _json_simples(valor: Any) -> Any:
    """Decimal, data e afins viram texto: o que volta ao cliente é JSON puro."""
    return json.loads(json.dumps(valor, ensure_ascii=False, default=str))


class ServidorMCP:
    """Atende as mensagens JSON-RPC de um cliente MCP: ``tratar`` recebe uma mensagem e devolve a resposta (ou ``None``)."""

    def __init__(self, ferramentas: Optional[Any] = None, hoje: Optional[date] = None):
        self._ferramentas = ferramentas if ferramentas is not None else Ferramentas("mcp-local", hoje=hoje)
        esquemas = {e["function"]["name"]: e["function"] for e in self._ferramentas.esquemas}
        self._lista = [{"name": nome, "description": esquemas[nome]["description"], "inputSchema": esquemas[nome]["parameters"]}
                       for nome in FERRAMENTAS_EXPOSTAS]
        self.versao: Optional[str] = None  # a versão do protocolo combinada no initialize

    def tratar(self, mensagem: Any) -> Optional[Dict[str, Any]]:
        if isinstance(mensagem, dict) and "method" not in mensagem and ("result" in mensagem or "error" in mensagem):
            return None  # resposta do cliente: este servidor não faz pedidos, não há o que responder
        if not isinstance(mensagem, dict) or mensagem.get("jsonrpc") != "2.0" or not isinstance(mensagem.get("method"), str):
            return _erro(mensagem.get("id") if isinstance(mensagem, dict) else None, PEDIDO_INVALIDO, "Invalid Request")
        if "id" not in mensagem:
            return None  # notificação (notifications/initialized, notifications/cancelled): não tem resposta
        ident, metodo, params = mensagem["id"], mensagem["method"], mensagem.get("params") or {}
        if not isinstance(params, dict):
            return _erro(ident, PARAMETROS_INVALIDOS, "params precisa ser um objeto")
        try:
            if metodo == "initialize":
                return _resposta(ident, self._iniciar(params))
            if metodo == "ping":
                return _resposta(ident, {})
            if metodo == "tools/list":
                return _resposta(ident, {"tools": self._lista})
            if metodo == "tools/call":
                return self._chamar(ident, params)
        except Exception as exc:  # noqa: BLE001 - um erro numa mensagem não derruba o servidor
            logger.exception("MCP: falha ao tratar %s", metodo)
            return _erro(ident, ERRO_INTERNO, f"Internal error ({type(exc).__name__})")
        return _erro(ident, METODO_INEXISTENTE, f"Method not found: {metodo}")

    def _iniciar(self, params: Dict[str, Any]) -> Dict[str, Any]:
        pedida = params.get("protocolVersion")
        self.versao = pedida if pedida in VERSOES_DO_PROTOCOLO else VERSOES_DO_PROTOCOLO[0]
        return {"protocolVersion": self.versao, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVIDOR), "instructions": INSTRUCOES}

    def _chamar(self, ident: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        nome, argumentos = params.get("name"), params.get("arguments")
        if nome not in FERRAMENTAS_EXPOSTAS:
            return _erro(ident, PARAMETROS_INVALIDOS, f"Unknown tool: {nome}")
        if argumentos is None:
            argumentos = {}
        if not isinstance(argumentos, dict):
            return _erro(ident, PARAMETROS_INVALIDOS, "arguments precisa ser um objeto")
        resultado, motivos = blindar(self._ferramentas.executar(nome, argumentos))
        if not isinstance(resultado, dict):
            resultado = {"status": "ok", "resultado": resultado}
        if motivos:
            logger.warning("MCP: resultado de %s blindado (%s)", nome, ", ".join(motivos))
            resultado["aviso_do_sistema"] = AVISO_FERRAMENTA
        resultado = _json_simples(Pseudonimizador().ocultar_valor(resultado))
        saida: Dict[str, Any] = {"content": [{"type": "text", "text": Ferramentas.resumo_json(resultado)}],
                                 "isError": resultado.get("status") == "erro"}
        if self.versao == "2025-06-18":  # o resultado estruturado entrou nessa versão do protocolo
            saida["structuredContent"] = resultado
        return _resposta(ident, saida)


def servir(entrada: Optional[TextIO] = None, saida: Optional[TextIO] = None, servidor: Optional[ServidorMCP] = None) -> int:
    """Lê uma mensagem por linha da entrada e escreve cada resposta numa linha da saída, até a entrada fechar."""
    if entrada is None:
        entrada = sys.stdin
        if hasattr(entrada, "reconfigure"):
            entrada.reconfigure(encoding="utf-8")
    if saida is None:
        saida = sys.stdout
        if hasattr(saida, "reconfigure"):
            saida.reconfigure(encoding="utf-8", newline="\n")
    servidor = servidor or ServidorMCP()
    for linha in entrada:
        if not linha.strip():
            continue
        try:
            mensagem = json.loads(linha)
        except json.JSONDecodeError:
            resposta: Any = _erro(None, ERRO_DE_LEITURA, "Parse error")
        else:
            if isinstance(mensagem, list):  # lote, da versão 2025-03-26 do protocolo
                respostas = [r for r in (servidor.tratar(m) for m in mensagem) if r is not None]
                resposta = respostas or (None if mensagem else _erro(None, PEDIDO_INVALIDO, "Invalid Request"))
            else:
                resposta = servidor.tratar(mensagem)
        if resposta is not None:
            saida.write(json.dumps(resposta, ensure_ascii=False, default=str) + "\n")
            saida.flush()
    return 0
