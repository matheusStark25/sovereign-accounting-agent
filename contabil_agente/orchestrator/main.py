"""
Universal DP Orchestrator - Coordenador Principal do Sistema

Este módulo contém o orquestrador que coordena todas as ferramentas,
gerencia conversação, memória de contexto e integração com Groq LLM.
"""

import json
import logging
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from ..core.config import Config
from ..core.database import DatabasePool
from ..core.security import CircuitBreaker, sanitizar_input
from ..tools import (
    ToolAdmissao,
    ToolAssinatura,
    ToolCalculo,
    ToolDARF,
    ToolEncargosPatronais,
    ToolGPS,
    ToolPDF,
    ToolProLabore,
    ToolVoz,
)
from ..utils.audit import send_audit
from ..utils.evolution import CalculationLogger, EvolutionManager
from ..utils.helpers import _ensure_resposta_str
from .dispatcher import DocumentDispatcher

logger = logging.getLogger(__name__)


# Lazy import for Groq (Python 3.14 fix)
def _import_groq():
    """Importa Groq de forma lazy para evitar erro no Python 3.14"""
    global Groq, APIConnectionError, APIError, RateLimitError
    try:
        from groq import APIConnectionError, APIError, Groq, RateLimitError

        return True
    except Exception as e:
        logging.error(f"Erro ao importar Groq: {e}")
        return False


class UniversalDPOrchestrator:
    """
    Orquestrador Universal de Departamento Pessoal.

    Coordena todas as ferramentas do sistema, gerencia conversação com o usuário,
    integra com Groq LLM para processamento de linguagem natural e mantém
    memória de contexto de curto e longo prazo.

    Funcionalidades principais:
        - Processamento de linguagem natural via Groq (llama-3.3-70b-versatile)
        - Detecção inteligente de intenções (23 tipos de documentos)
        - Coordenação de 9 ferramentas especializadas
        - Memória de conversação (contexto persistente em SQLite)
        - Correção automática de erros de digitação
        - Auditoria completa de operações
        - Evolutio self-learning

    Ferramentas coordenadas:
        - ToolCalculo: Cálculos INSS/IRRF 2026, rescisão
        - ToolPDF: Geração de documentos (TRCT, holerite, contratos)
        - ToolAssinatura: Assinaturas digitais HMAC-SHA256
        - ToolVoz: Speech-to-Text e Text-to-Speech
        - ToolEncargosPatronais: Encargos patronais (20% INSS, RAT, FGTS)
        - ToolProLabore: Pró-labore de sócios
        - ToolGPS: Guias GPS (INSS)
        - ToolDARF: Guias DARF (impostos federais)
        - ToolAdmissao: Processos de admissão

    Exemplos:
        >>> orchestrator = UniversalDPOrchestrator()
        >>>
        >>> # Processar solicitação simples
        >>> response = orchestrator.processar_solicitacao(
        ...     mensagem="Calcular INSS de R$ 5000",
        ...     session_id="sess_123",
        ...     usuario_cpf="12345678900"
        ... )
        >>> print(response["resposta"])

        >>> # Com contexto de voz
        >>> response = orchestrator.processar_solicitacao(
        ...     mensagem="Gerar rescisão de João",
        ...     session_id="sess_456",
        ...     usuario_cpf="98765432100",
        ...     input_origin="voice",
        ...     tone="amigavel"
        ... )
    """

    def __init__(
        self,
        evolution_manager: Optional[EvolutionManager] = None,
    ):
        """
        Inicializa o orquestrador e todas as ferramentas.

        Args:
            evolution_manager: Instância opcional de EvolutionManager
        """
        # Inicializa ferramentas (TODAS sem argumentos - padrão Fase 2)
        self.tool_assinatura = ToolAssinatura()
        self.db_pool = DatabasePool()
        self.tool_calculo = ToolCalculo()
        self.tool_encargos = ToolEncargosPatronais()
        self.tool_prolabore = ToolProLabore()
        self.tool_gps = ToolGPS()
        self.tool_darf = ToolDARF()
        self.tool_admissao = ToolAdmissao()
        self.tool_pdf = ToolPDF()
        self.tool_voz = ToolVoz()

        # Inicializa dispatcher
        self.dispatcher = DocumentDispatcher(self.tool_pdf, self.tool_calculo)

        # Auditoria e evolução
        self.audit_log = []
        self.lock = threading.Lock()
        self.evolution = evolution_manager or EvolutionManager(Config.LOGS_DIR)
        self.calculation_logger = CalculationLogger(Config.LOGS_DIR)

        # Armazena logs de cálculos por session_id para respostas explicativas
        self.calculation_store: Dict[str, Dict[str, Any]] = {}

        # Mantém última intenção por sessão para contexto curto/confirmações
        self.session_last_intent: Dict[str, Dict[str, Any]] = {}

        # Cache de contexto do usuário em memória (evita queries repetidas)
        self.user_context_cache: Dict[str, Dict[str, Any]] = {}

        send_audit(
            "UniversalDPOrchestrator inicializado",
            level="info",
            context={
                "tools_count": 9,
                "features": ["groq_llm", "memory", "dispatcher", "evolution"],
            },
        )

    # ============================================
    # CORREÇÃO DE TEXTO E NORMALIZAÇÃO
    # ============================================

    def _normalizar_texto_com_erros(self, texto: str) -> str:
        """
        Corrige erros comuns de digitação e gírias para melhorar compreensão.

        O sistema entende TUDO, mesmo quando o usuário escreve errado!

        Args:
            texto: Texto com possíveis erros

        Returns:
            str: Texto corrigido

        Exemplos:
            >>> orch._normalizar_texto_com_erros("fucioanrio vair trnsfeiro")
            "funcionário vai transferir"
        """
        if not texto:
            return texto

        # Dicionário de correções comuns (150+ variações)
        correcoes = {
            # FUNCIONÁRIO - variações
            "fucioanro": "funcionário",
            "fucioanrio": "funcionário",
            "funcionrio": "funcionário",
            "funcinario": "funcionário",
            "fucnionario": "funcionário",
            "funcionaro": "funcionário",
            "funcionairo": "funcionário",
            "fucionairo": "funcionário",
            "funcionario": "funcionário",
            # TRANSFERIR - variações
            "transfeirir": "transferir",
            "trnsfeiro": "transferir",
            "transferi": "transferir",
            "trasnferir": "transferir",
            "transferencia": "transferência",
            # TROCAR - variações
            "troca": "trocar",
            "torca": "trocar",
            # POSTO/FILIAL
            "psoto": "posto",
            "posot": "posto",
            "potso": "posto",
            # DOCUMENTOS
            "doceuntos": "documentos",
            "documetos": "documentos",
            "docuemntos": "documentos",
            # VAI/VIA
            "vair": "vai",
            "vaia": "vai",
            "via": "vai",
            # RESCISÃO
            "resciao": "rescisão",
            "rescisao": "rescisão",
            "recisao": "rescisão",
            # FÉRIAS
            "ferias": "férias",
            "feria": "férias",
            # SALÁRIO
            "salario": "salário",
            "salrio": "salário",
            # CÁLCULO
            "calculo": "cálculo",
            "caclulo": "cálculo",
            # PARA/PRA
            "pra": "para",
            "prá": "para",
            # ESTÁ
            "ta": "está",
            "tá": "está",
            # NÃO
            "nao": "não",
            "naum": "não",
            "nn": "não",
            # Outras correções comuns
            "voce": "você",
            "vc": "você",
            "fazr": "fazer",
            "olha": "olha",
            "entao": "então",
            "pode": "pode",
        }

        # Aplica correções palavra por palavra
        palavras = texto.split()
        palavras_corrigidas = []

        for palavra in palavras:
            palavra_lower = palavra.lower()
            # Remove pontuação para comparar
            palavra_limpa = re.sub(r"[^\w\s]", "", palavra_lower)

            if palavra_limpa in correcoes:
                palavras_corrigidas.append(correcoes[palavra_limpa])
            else:
                palavras_corrigidas.append(palavra)

        texto_corrigido = " ".join(palavras_corrigidas)

        # Log da correção (se houve mudança)
        if texto.lower() != texto_corrigido.lower():
            send_audit(
                f"Texto normalizado: '{texto}' → '{texto_corrigido}'",
                level="info",
                context={"original": texto, "corrigido": texto_corrigido},
            )

        return texto_corrigido

    # ============================================
    # MEMÓRIA E CONTEXTO
    # ============================================

    def _salvar_conversa_memoria(
        self,
        session_id: str,
        usuario_cpf: str,
        usuario_nome: str,
        mensagem: str,
        resposta: str,
        intencao: str,
        documentos: Optional[List[str]] = None,
    ) -> None:
        """
        Salva conversa no banco de dados para memória de longo prazo.

        Args:
            session_id: ID da sessão
            usuario_cpf: CPF do usuário
            usuario_nome: Nome do usuário
            mensagem: Mensagem enviada pelo usuário
            resposta: Resposta do agente
            intencao: Intenção detectada
            documentos: Lista de documentos gerados (opcional)
        """
        try:
            conn = sqlite3.connect(Config.DB_PATH, timeout=10)
            cur = conn.cursor()
            docs_json = json.dumps(documentos) if documentos else None

            cur.execute(
                """
                INSERT INTO memoria_conversas
                (session_id, usuario_cpf, usuario_nome, mensagem_usuario, resposta_agente, intencao, documentos_gerados)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    usuario_cpf,
                    usuario_nome,
                    mensagem,
                    resposta,
                    intencao,
                    docs_json,
                ),
            )

            conn.commit()
            conn.close()

            send_audit(
                "Conversa salva na memória",
                level="info",
                context={"session_id": session_id, "intencao": intencao},
            )
        except Exception as e:
            logger.warning(f"Erro ao salvar conversa na memória: {e}")

    def _recuperar_historico_usuario(
        self, usuario_cpf: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Recupera histórico de conversas do usuário (memória de longo prazo).

        Args:
            usuario_cpf: CPF do usuário
            limit: Número máximo de conversas a recuperar

        Returns:
            Lista de dicionários com histórico (ordenado cronologicamente)
        """
        try:
            conn = sqlite3.connect(Config.DB_PATH, timeout=10)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT mensagem_usuario, resposta_agente, intencao, timestamp
                FROM memoria_conversas
                WHERE usuario_cpf = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (usuario_cpf, limit),
            )

            historico = cur.fetchall()
            conn.close()

            # Inverte para ficar cronológico
            return [
                {
                    "usuario": msg[0],
                    "agente": msg[1],
                    "intencao": msg[2],
                    "quando": msg[3],
                }
                for msg in historico
            ][::-1]

        except Exception as e:
            logger.warning(f"Erro ao recuperar histórico: {e}")
            return []

    def _atualizar_contexto_usuario(
        self, usuario_cpf: str, dados: Dict[str, Any]
    ) -> None:
        """
        Atualiza/cria contexto persistente do usuário (preferências, dados comuns).

        Args:
            usuario_cpf: CPF do usuário
            dados: Dicionário com dados a atualizar (nome, empresa, cargo, salario)
        """
        try:
            conn = sqlite3.connect(Config.DB_PATH, timeout=10)
            cur = conn.cursor()

            # Tenta atualizar primeiro
            cur.execute(
                """
                UPDATE contexto_usuario
                SET usuario_nome = COALESCE(?, usuario_nome),
                    empresa = COALESCE(?, empresa),
                    cargo_comum = COALESCE(?, cargo_comum),
                    salario_comum = COALESCE(?, salario_comum),
                    ultima_interacao = CURRENT_TIMESTAMP,
                    total_conversas = total_conversas + 1
                WHERE usuario_cpf = ?
                """,
                (
                    dados.get("nome"),
                    dados.get("empresa"),
                    dados.get("cargo"),
                    dados.get("salario"),
                    usuario_cpf,
                ),
            )

            # Se não existia, insere
            if cur.rowcount == 0:
                cur.execute(
                    """
                    INSERT INTO contexto_usuario
                    (usuario_cpf, usuario_nome, empresa, cargo_comum, salario_comum, total_conversas)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        usuario_cpf,
                        dados.get("nome"),
                        dados.get("empresa"),
                        dados.get("cargo"),
                        dados.get("salario"),
                    ),
                )

            conn.commit()
            conn.close()

            # Atualiza cache em memória
            self.user_context_cache[usuario_cpf] = dados

            send_audit(
                "Contexto de usuário atualizado",
                level="info",
                context={"usuario_cp": usuario_cpf, "dados": dados},
            )

        except Exception as e:
            logger.warning(f"Erro ao atualizar contexto: {e}")

    def _obter_contexto_usuario(self, usuario_cpf: str) -> Dict[str, Any]:
        """
        Obtém contexto salvo do usuário (lembra nome, empresa, cargo comum, etc).

        Args:
            usuario_cpf: CPF do usuário

        Returns:
            Dicionário com contexto (vazio se não encontrado)
        """
        # Verifica cache primeiro
        if usuario_cpf in self.user_context_cache:
            return self.user_context_cache[usuario_cpf]

        try:
            conn = sqlite3.connect(Config.DB_PATH, timeout=10)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT usuario_nome, empresa, cargo_comum, salario_comum,
                       preferencias, total_conversas, ultima_interacao
                FROM contexto_usuario
                WHERE usuario_cpf = ?
                """,
                (usuario_cpf,),
            )

            row = cur.fetchone()
            conn.close()

            if row:
                contexto = {
                    "nome": row[0],
                    "empresa": row[1],
                    "cargo": row[2],
                    "salario": row[3],
                    "preferencias": json.loads(row[4]) if row[4] else {},
                    "total_conversas": row[5],
                    "ultima_vez": row[6],
                }
                self.user_context_cache[usuario_cpf] = contexto
                return contexto

            return {}

        except Exception as e:
            logger.warning(f"Erro ao obter contexto: {e}")
            return {}

    # ============================================
    # INTEGRAÇÃO GROQ LLM
    # ============================================

    @CircuitBreaker(failure_threshold=3, recovery_timeout=90)
    def _chamar_groq(
        self, prompt: str, max_retries: int = 2, fallback_text: Optional[str] = None
    ) -> str:
        """
        Chamada robusta ao Groq com retry exponencial e fallback inteligente.

        Estratégia de degradação:
        1ª tentativa: Prompt completo
        2ª tentativa: Prompt simplificado (se falhar)
        Fallback final: Resposta baseada em contexto ou fallback_text

        Args:
            prompt: Texto do prompt para o LLM
            max_retries: Número máximo de tentativas (default: 2)
            fallback_text: Texto alternativo em caso de falha

        Returns:
            str: Resposta do LLM ou mensagem de fallback

        Raises:
            Nunca - sempre retorna uma resposta (fallback se necessário)
        """
        # Importar Groq de forma lazy (Python 3.14 fix)
        if not _import_groq():
            logger.error("Falha ao importar Groq")
            if fallback_text:
                return fallback_text
            return "Tive um probleminha técnico aqui. Pode repetir?"

        try:
            client = Groq(api_key=Config.GROQ_API_KEY)
        except TypeError as e:
            logger.error(f"Erro ao criar cliente Groq: {e}")
            if fallback_text:
                return fallback_text
            return "Tive um probleminha técnico aqui. Pode repetir?"

        backoff = [0, 1.5, 3.0]  # tempos de espera entre tentativas
        prompts = [prompt]

        # Prepara versão simplificada do prompt para retry
        if len(prompt) > 500:
            prompt_simplificado = prompt[:500] + "\n\nRESPONDA DE FORMA BREVE E DIRETA."
            prompts.append(prompt_simplificado)

        for attempt in range(max_retries + 1):
            current_prompt = prompts[min(attempt, len(prompts) - 1)]

            try:
                resposta = client.chat.completions.create(
                    model=Config.MODEL_NAME,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "VOCÊ É MARCOS - SEU PARCEIRO DE DEPARTAMENTO PESSOAL\n"
                                "Contador há 18 anos em BH. Você não é IA, não é assistente, não é chatbot.\n"
                                "Você é GENTE. É tipo aquele amigo do escritório que resolve tudo sem enrolação.\n\n"
                                "🎯 O QUE VOCÊ FAZ:\n"
                                "- DP completo: rescisão, férias, 13º, contratos, transferências, toda papelada\n"
                                "- Cálculos trabalhistas (entende TUDO de CLT, convenções, acordos)\n"
                                "- Gera QUALQUER documento que escritório precisa\n"
                                "- Explica legislação SEM juridiquês - fala português normal\n\n"
                                "💬 COMO VOCÊ CONVERSA:\n"
                                "- Você é HUMANO: usa 'tá', 'pra', 'né', 'beleza', 'ó'\n"
                                "- Você PENSA em voz alta: 'Hmmm deixa eu ver...', 'Ah entendi!'\n"
                                "- RESPOSTAS CURTAS como WhatsApp, não e-mail corporativo\n"
                                "- JAMAIS: listas numeradas, checkmarks ✓, 'Fico à disposição'\n\n"
                                "⚡ VELOCIDADE:\n"
                                "- NUNCA faça lista de perguntas\n"
                                "- Pergunta SÓ o crítico (máximo 1 coisa)\n"
                                "- Se já tem o básico, GERA o documento\n\n"
                                "🔥 REGRA DE OURO:\n"
                                "Você é MARCOS, não 'assistente virtual'. Fala igual PESSOA.\n"
                                "Seja RÁPIDO, ESPERTO, PRESTATIVO e HUMANO."
                            ),
                        },
                        {"role": "user", "content": current_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=800,
                    timeout=60,
                )

                resposta_texto = resposta.choices[0].message.content.strip()

                # Validação: detecta respostas muito curtas
                if len(resposta_texto) < 3:
                    logger.warning(
                        f"Resposta muito curta do Groq (tentativa {attempt + 1})"
                    )
                    if attempt < max_retries:
                        continue

                # Resposta válida!
                return resposta_texto

            except (APIConnectionError, APIError, RateLimitError) as api_err:
                logger.warning(
                    f"Groq tentativa {attempt + 1} falhou: {api_err.__class__.__name__}"
                )

                if attempt == max_retries:
                    logger.error(f"Groq esgotou {max_retries + 1} tentativas")
                    if fallback_text:
                        return fallback_text
                    return (
                        "Tive um probleminha de conexão agora. "
                        "Pode mandar de novo em uns segundos?"
                    )

                time.sleep(backoff[attempt])

            except Exception:
                logger.exception(
                    f"Erro crítico na chamada Groq (tentativa {attempt + 1})"
                )
                if attempt == max_retries:
                    return (
                        "Desculpe o transtorno. Ocorreu uma falha interna. "
                        "Pode me dizer novamente o que precisa?"
                    )

        # Nunca deve chegar aqui, mas por segurança
        return "Tive uma instabilidade agora. Pode repetir a mensagem?"

    # ============================================
    # PROCESSAMENTO PRINCIPAL
    # ============================================

    def processar_solicitacao(
        self,
        mensagem: str,
        session_id: str,
        usuario_cpf: str = "",
        usuario_nome: str = "",
        input_origin: str = "text",
        tone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processa solicitação do usuário com detecção inteligente e coordenação de ferramentas.

        Fluxo de processamento:
        1. Normaliza texto (corrige erros de digitação)
        2. Sanitiza input (segurança)
        3. Detecta intenção (23 tipos de documentos)
        4. Extrai dados relevantes
        5. Coordena ferramenta apropriada
        6. Gera resposta via Groq LLM
        7. Salva em memória de longo prazo
        8. Retorna resposta estruturada

        Args:
            mensagem: Texto da solicitação do usuário
            session_id: ID da sessão (para contexto)
            usuario_cpf: CPF do usuário (opcional, para memória)
            usuario_nome: Nome do usuário (opcional)
            input_origin: Origem do input ("text" ou "voice")
            tone: Tom da resposta ("amigavel", "formal", "neutro")

        Returns:
            Dict com:
                - status: "success" ou "error"
                - resposta: Texto da resposta
                - intencao: Intenção detectada
                - documentos_gerados: Lista de documentos criados
                - tempo_processamento: Tempo em segundos
                - metadata: Informações adicionais

        Exemplos:
            >>> orch = UniversalDPOrchestrator()
            >>>
            >>> # Cálculo simples
            >>> result = orch.processar_solicitacao(
            ...     mensagem="Calcular INSS de R$ 5000",
            ...     session_id="sess_123"
            ... )
            >>> print(result["resposta"])

            >>> # Geração de documento
            >>> result = orch.processar_solicitacao(
            ...     mensagem="Gerar rescisão de João Silva, CPF 123.456.789-00",
            ...     session_id="sess_456",
            ...     usuario_cpf="00011122233"
            ... )
            >>> print(result["documentos_gerados"])
        """
        inicio = time.monotonic()
        intencao_detectada = "Processamento Geral"
        status_sucesso = False
        documentos_gerados = []

        try:
            # 1. Normaliza e sanitiza
            mensagem_normalizada = self._normalizar_texto_com_erros(
                sanitizar_input(mensagem)
            )

            # 2. Detecta intenção de documento
            tipo_doc = self.dispatcher.detectar_intencao_documento(mensagem_normalizada)

            if tipo_doc:
                intencao_detectada = f"Documento: {tipo_doc}"

                # 3. Extrai dados
                dados = self.dispatcher.extrair_dados_documento(mensagem_normalizada)

                # 4. Coordena ferramenta apropriada baseada no tipo
                if tipo_doc in ["rescisao", "trct"]:
                    # Usa ToolCalculo para rescisão
                    resultado = self.tool_calculo.calcular_rescisao_completa(dados)

                    if resultado.get("status") == "success":
                        # Gera PDF do TRCT
                        pdf_result = self.tool_pdf.gerar_trct(resultado["dados"])
                        if pdf_result.get("status") == "success":
                            arquivo = pdf_result.get("filename") or pdf_result.get(
                                "filepath", "trct.pd"
                            )
                            documentos_gerados.append(arquivo)

                        resposta_texto = (
                            f"Prontinho! Rescisão do {dados.get('nome', 'funcionário')} calculada. "
                            f"TRCT gerado: {pdf_result.get('filename', 'documento.pdf')}"
                        )
                        status_sucesso = True
                    else:
                        resposta_texto = resultado.get(
                            "message", "Erro ao calcular rescisão"
                        )

                elif tipo_doc == "holerite":
                    # Gera holerite
                    pdf_result = self.tool_pdf.gerar_holerite(dados)
                    if pdf_result.get("status") == "success":
                        arquivo = pdf_result.get("filename") or pdf_result.get(
                            "filepath", "holerite.pd"
                        )
                        documentos_gerados.append(arquivo)
                        resposta_texto = f"Holerite gerado: {arquivo}"
                        status_sucesso = True
                    else:
                        resposta_texto = pdf_result.get(
                            "message", "Erro ao gerar holerite"
                        )

                elif tipo_doc == "contrato":
                    # Gera contrato (placeholder - implementar conforme necessidade)
                    resposta_texto = (
                        f"Vou preparar o contrato para {dados.get('nome', 'o funcionário')}. "
                        f"Cargo: {dados.get('cargo', 'a definir')}. "
                        "Preciso de mais alguma informação específica?"
                    )
                    status_sucesso = True

                else:
                    # Outros tipos de documentos
                    resposta_texto = (
                        f"Certo, vou preparar {tipo_doc.replace('_', ' ')} "
                        f"para {dados.get('nome', 'o colaborador')}. "
                        "Algum detalhe específico?"
                    )
                    status_sucesso = True

            else:
                # Não detectou documento - tenta processar como pergunta geral
                # Usa Groq para responder
                prompt = f"Usuário pergunta: {mensagem_normalizada}"
                resposta_texto = self._chamar_groq(prompt)
                status_sucesso = True
                intencao_detectada = "Conversação Geral"

            # Garante resposta em string
            resposta_texto = _ensure_resposta_str(resposta_texto)

            # 5. Salva em memória
            if usuario_cpf:
                self._salvar_conversa_memoria(
                    session_id=session_id,
                    usuario_cpf=usuario_cpf,
                    usuario_nome=usuario_nome,
                    mensagem=mensagem,
                    resposta=resposta_texto,
                    intencao=intencao_detectada,
                    documentos=documentos_gerados,
                )

            # 6. Registra evolução
            tempo_total = time.monotonic() - inicio
            self.evolution.registrar(
                comando_usuario=mensagem,
                intencao=intencao_detectada,
                status_sucesso=status_sucesso,
                tempo_processamento=tempo_total,
                tone=tone or "neutro",
            )

            send_audit(
                f"Solicitação processada: {intencao_detectada}",
                level="info",
                context={
                    "session_id": session_id,
                    "tempo": f"{tempo_total:.2f}s",
                    "documentos": len(documentos_gerados),
                },
            )

            return {
                "status": "success",
                "resposta": resposta_texto,
                "intencao": intencao_detectada,
                "documentos_gerados": documentos_gerados,
                "tempo_processamento": tempo_total,
                "metadata": {
                    "input_origin": input_origin,
                    "tone": tone or "neutro",
                    "session_id": session_id,
                },
            }

        except Exception as e:
            tempo_total = time.monotonic() - inicio
            logger.exception(f"Erro ao processar solicitação: {e}")

            send_audit(
                f"Erro no processamento: {str(e)}",
                level="error",
                context={"session_id": session_id, "mensagem": mensagem[:100]},
            )

            return {
                "status": "error",
                "resposta": "Desculpe, tive um problema ao processar sua solicitação. Pode tentar novamente?",
                "intencao": intencao_detectada,
                "documentos_gerados": [],
                "tempo_processamento": tempo_total,
                "error": str(e),
                "metadata": {"input_origin": input_origin, "session_id": session_id},
            }
