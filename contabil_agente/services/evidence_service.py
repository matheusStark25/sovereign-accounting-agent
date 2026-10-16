"""
Sistema de Evidências Legais e Auditoria
Registra todas as operações com hash SHA-256 para validade jurídica

Funcionalidades:
- Registro de evidências com hash SHA-256
- Timestamp preciso de operações
- Rastreabilidade completa de documentos
- Prova de aceite e assinaturas
- Logs imutáveis para auditoria
"""

import hashlib
import json
import logging
import tempfile
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
# Ensure default StreamHandler to avoid silent logging when used standalone
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)


class RegistroEvidencia:
    """Registro individual de evidência legal"""

    def __init__(
        self,
        tipo: str,
        descricao: str,
        dados: Dict,
        arquivo_relacionado: Optional[str] = None,
    ):
        """
        Cria registro de evidência

        Args:
            tipo: Tipo de evidência (calculo, assinatura, geracao_pdf, etc.)
            descricao: Descrição da operação
            dados: Dados da evidência
            arquivo_relacionado: Caminho do arquivo relacionado
        """
        self.id_evidencia = str(uuid.uuid4())
        self.tipo = tipo
        self.descricao = descricao
        self.dados = dados
        self.arquivo_relacionado = arquivo_relacionado
        self.timestamp = datetime.now()
        self.timestamp_iso = self.timestamp.isoformat()

        # Hash SHA-256 dos dados
        self.hash_dados = self._calcular_hash_dados()

        # Hash do arquivo relacionado (se existir)
        self.hash_arquivo = None
        if arquivo_relacionado and Path(arquivo_relacionado).exists():
            self.hash_arquivo = self._calcular_hash_arquivo(arquivo_relacionado)

    def _calcular_hash_dados(self) -> str:
        """Calcula hash SHA-256 dos dados da evidência"""
        dados_json = json.dumps(self.dados, sort_keys=True, default=str)
        return hashlib.sha256(dados_json.encode("utf-8")).hexdigest()

    def _calcular_hash_arquivo(self, caminho_arquivo: str) -> str:
        """Calcula hash SHA-256 de um arquivo"""
        sha256_hash = hashlib.sha256()
        with open(caminho_arquivo, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def to_dict(self) -> Dict:
        """Converte registro para dicionário"""
        return {
            "id_evidencia": self.id_evidencia,
            "tipo": self.tipo,
            "descricao": self.descricao,
            "timestamp": self.timestamp_iso,
            "dados": self.dados,
            "arquivo_relacionado": self.arquivo_relacionado,
            "hash_dados": self.hash_dados,
            "hash_arquivo": self.hash_arquivo,
        }

    def to_json(self) -> str:
        """Converte registro para JSON"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass
class EvidenceConfig:
    base_dir: Optional[str] = None
    filename: str = "evidencias_assinatura.log"
    rotate_size: int = 10 * 1024 * 1024  # 10 MB
    max_backups: int = 5
    memory_only: bool = False
    # allow extra kwargs
    kwargs: dict = field(default_factory=dict)


class GerenciadorEvidencias:
    """Gerenciador de evidências com singleton thread-safe, lazy init,
    fallback para diretório temporário e modo memory-only.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # Singleton instantiation
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(GerenciadorEvidencias, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict] = None, **kwargs):
        # Lazy initialization guard
        if getattr(self, "_initialized", False):
            return

        # Merge provided config
        cfg_kwargs = dict(config or {})
        cfg_kwargs.update(kwargs)
        # Extract known config keys to avoid TypeError from unexpected kwargs
        known = {}
        for attr in (
            "base_dir",
            "filename",
            "rotate_size",
            "max_backups",
            "memory_only",
        ):
            if attr in cfg_kwargs:
                known[attr] = cfg_kwargs.pop(attr)
        self.config = EvidenceConfig(**known)
        # Keep any extra keys available
        self.config.kwargs.update(cfg_kwargs)

        self._write_lock = threading.Lock()
        self._memory_store: List[RegistroEvidencia] = []
        self._log_dir = None
        self.arquivo_log = None

        # Resolve base directory hierarchy without using __file__.parent.parent
        self._resolve_base_dir()

        # If not memory only, ensure log file exists and is writable (smoke test)
        if not self.config.memory_only:
            self._ensure_log_file()

        logger.info("Gerenciador de evidências inicializado: %s" % (self.arquivo_log,))
        self._initialized = True

    def _inicializar_log(self):
        """Inicializa arquivo de log com cabeçalho"""
        cabecalho = {
            "sistema": "Sistema de Evidências Legais",
            "versao": "1.0.0",
            "inicializado_em": datetime.now().isoformat(),
            "proposito": "Registro de evidências com hash SHA-256 para validade jurídica",
            "formato": "Cada linha contém um registro JSON com evidência completa",
            "imutavel": "Este log é append-only e não deve ser modificado",
        }
        try:
            with open(self.arquivo_log, "w", encoding="utf-8") as f:
                f.write("# SISTEMA DE EVIDÊNCIAS LEGAIS\n")
                f.write("# Este arquivo contém registros imutáveis de operações\n")
                f.write("# Cada linha após o cabeçalho é um registro JSON válido\n")
                f.write("# ATENÇÃO: NÃO MODIFICAR ESTE ARQUIVO MANUALMENTE\n")
                f.write("#" * 80 + "\n")
                f.write(json.dumps(cabecalho, indent=2, ensure_ascii=False) + "\n")
                f.write("#" * 80 + "\n\n")
        except Exception:
            logger.exception(
                "Falha ao inicializar arquivo de evidências: %s", self.arquivo_log
            )

    def _resolve_base_dir(self):
        """Resolve o diretório base para armazenar evidências usando a
        hierarquia: explicit config.base_dir -> ENV EVIDENCIAS_PATH ->
        ~/.contabil_agente -> tempfile.gettempdir()
        Também realiza um smoke-test de permissões e migra para fallback
        se necessário.
        """
        # 1) explicit config
        cand = None
        if self.config.base_dir:
            cand = Path(self.config.base_dir)

        # 2) env var
        if cand is None:
            envp = os.environ.get("EVIDENCIAS_PATH")
            if envp:
                cand = Path(envp)

        # 3) home fallback
        if cand is None:
            cand = Path.home() / ".contabil_agente"

        # ensure try to create and smoke-test
        try:
            cand.mkdir(parents=True, exist_ok=True)
            # smoke test: create and remove a temp file
            tf = cand / (".perm_test_%s" % uuid.uuid4().hex)
            with open(tf, "w") as f:
                f.write("ok")
            tf.unlink()
            self._log_dir = cand
        except Exception:
            # fallback to system temp dir
            fallback = Path(tempfile.gettempdir()) / "contabil_evidencias"
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                self._log_dir = fallback
                logger.warning(
                    "Permissão negada para %s; usando fallback temporário %s",
                    cand,
                    fallback,
                )
            except Exception:
                # last resort: use tempfile.gettempdir() directly
                self._log_dir = Path(tempfile.gettempdir())
                logger.warning(
                    "Permissão negada para %s e fallback; usando %s",
                    cand,
                    self._log_dir,
                )

        # set arquivo_log path
        self.arquivo_log = self._log_dir / self.config.filename

    def _ensure_log_file(self):
        """Ensure the log file exists and is writable; initialize if needed."""
        try:
            self.arquivo_log.parent.mkdir(parents=True, exist_ok=True)
            if not self.arquivo_log.exists():
                self._inicializar_log()
            # test write
            tf = self.arquivo_log.parent / (".write_test_%s" % uuid.uuid4().hex)
            with open(tf, "w") as f:
                f.write("ok")
            tf.unlink()
        except Exception:
            # fallback to tempdir and mark warning
            fallback = Path(tempfile.gettempdir()) / "contabil_evidencias"
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                self.arquivo_log = fallback / self.config.filename
                if not self.arquivo_log.exists():
                    self._inicializar_log()
                logger.warning(
                    "Falha ao criar/escrever em %s; usando fallback %s",
                    self._log_dir,
                    fallback,
                )
            except Exception:
                # if still failing, switch to memory_only mode
                logger.exception(
                    "Falha crítica ao inicializar repositório de evidências; entrando em memory-only"
                )
                self.config.memory_only = True

    def _rotate_log(self):
        """Rotate current log file when exceeding configured size."""
        try:
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_name = "%s.%s" % (self.arquivo_log.name, ts)
            backup_path = self.arquivo_log.parent / backup_name
            try:
                self.arquivo_log.replace(backup_path)
            except Exception:
                # Try copy and remove
                import shutil

                shutil.copy2(self.arquivo_log, backup_path)
                try:
                    self.arquivo_log.unlink()
                except Exception:
                    pass

            # initialize new log
            self._inicializar_log()

            # cleanup older backups
            try:
                backups = sorted(
                    [
                        p
                        for p in self.arquivo_log.parent.iterdir()
                        if p.name.startswith(self.arquivo_log.name + ".")
                    ],
                    key=lambda p: p.stat().st_mtime,
                )
                while len(backups) > self.config.max_backups:
                    old = backups.pop(0)
                    try:
                        old.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            logger.exception("Erro durante rotação do arquivo de evidências")

    def registrar_evidencia(
        self,
        tipo: str,
        descricao: str,
        dados: Dict,
        arquivo_relacionado: Optional[str] = None,
    ) -> RegistroEvidencia:
        """
        Registra nova evidência no log

        Args:
            tipo: Tipo de evidência
            descricao: Descrição da operação
            dados: Dados da evidência
            arquivo_relacionado: Arquivo relacionado (opcional)

        Returns:
            RegistroEvidencia criado
        """
        evidencia = RegistroEvidencia(tipo, descricao, dados, arquivo_relacionado)

        # If memory_only mode, keep in memory and return
        if getattr(self.config, "memory_only", False):
            with self._write_lock:
                self._memory_store.append(evidencia)
            logger.info(
                "Evidência registrada em memória: %s - %s", evidencia.id_evidencia, tipo
            )
            return evidencia

        # Otherwise, attempt to write to disk with rotation and fallback
        with self._write_lock:
            try:
                # rotate if needed
                try:
                    if (
                        self.arquivo_log.exists()
                        and self.arquivo_log.stat().st_size >= self.config.rotate_size
                    ):
                        self._rotate_log()
                except Exception:
                    # if stat fails, ignore and proceed to write
                    pass

                # Write each evidence record as a single-line JSON to
                # ensure it can be read back line-by-line reliably.
                with open(self.arquivo_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(evidencia.to_dict(), ensure_ascii=False) + "\n")

                logger.info(
                    "Evidência registrada: %s - %s", evidencia.id_evidencia, tipo
                )
                logger.debug("Hash dados: %s", evidencia.hash_dados)
                if evidencia.hash_arquivo:
                    logger.debug("Hash arquivo: %s", evidencia.hash_arquivo)

                return evidencia
            except Exception:
                # On failure (e.g., disk full or permission), fallback to temp dir
                logger.exception(
                    "Falha ao gravar evidência em %s, migrando para tempdir",
                    self.arquivo_log,
                )
                try:
                    fallback_dir = Path(tempfile.gettempdir()) / "contabil_evidencias"
                    fallback_dir.mkdir(parents=True, exist_ok=True)
                    fallback_file = fallback_dir / self.config.filename
                    # attempt to write to fallback
                    with open(fallback_file, "a", encoding="utf-8") as f:
                        f.write(evidencia.to_json() + "\n")
                    # update internal pointer to fallback for subsequent writes
                    self.arquivo_log = fallback_file
                    logger.warning(
                        "Evidências agora sendo gravadas em fallback: %s", fallback_file
                    )
                    return evidencia
                except Exception:
                    # As a last resort, store in memory to avoid blocking caller
                    logger.exception(
                        "Falha ao gravar em fallback; registrando em memória"
                    )
                    with self._write_lock:
                        self._memory_store.append(evidencia)
                    return evidencia

    def registrar_calculo(
        self, tipo_calculo: str, dados_entrada: Dict, resultado: Dict
    ) -> RegistroEvidencia:
        """
        Registra evidência de cálculo

        Args:
            tipo_calculo: Tipo (folha, ferias, rescisao, etc.)
            dados_entrada: Dados de entrada do cálculo
            resultado: Resultado do cálculo

        Returns:
            RegistroEvidencia
        """
        dados = {
            "tipo_calculo": tipo_calculo,
            "entrada": dados_entrada,
            "resultado": resultado,
            "versao_tabelas": resultado.get("versao_tabelas", "1.0.0"),
        }

        return self.registrar_evidencia(
            tipo="calculo", descricao=f"Cálculo realizado: {tipo_calculo}", dados=dados
        )

    def registrar_geracao_pdf(
        self, tipo_documento: str, caminho_pdf: str, dados_documento: Dict
    ) -> RegistroEvidencia:
        """
        Registra evidência de geração de PDF

        Args:
            tipo_documento: Tipo do documento
            caminho_pdf: Caminho do PDF gerado
            dados_documento: Dados utilizados no documento

        Returns:
            RegistroEvidencia
        """
        dados = {
            "tipo_documento": tipo_documento,
            "caminho_pd": caminho_pdf,
            "dados_documento": dados_documento,
        }

        return self.registrar_evidencia(
            tipo="geracao_pd",
            descricao=f"PDF gerado: {tipo_documento}",
            dados=dados,
            arquivo_relacionado=caminho_pdf,
        )

    def registrar_assinatura(
        self,
        caminho_pdf: str,
        metodo_assinatura: str,
        resultado_assinatura: Dict,
        signatarios: Optional[List[Dict]] = None,
    ) -> RegistroEvidencia:
        """
        Registra evidência de assinatura digital

        Args:
            caminho_pdf: Caminho do PDF assinado
            metodo_assinatura: Método usado (docusign, icp-brasil)
            resultado_assinatura: Resultado da operação de assinatura
            signatarios: Lista de signatários (se aplicável)

        Returns:
            RegistroEvidencia
        """
        dados = {
            "caminho_pd": caminho_pdf,
            "metodo_assinatura": metodo_assinatura,
            "resultado": resultado_assinatura,
            "signatarios": signatarios or [],
        }

        return self.registrar_evidencia(
            tipo="assinatura",
            descricao=f"Documento assinado via {metodo_assinatura}",
            dados=dados,
            arquivo_relacionado=caminho_pdf,
        )

    def registrar_aceite(
        self, documento_id: str, usuario: Dict, aceite: bool, observacoes: str = ""
    ) -> RegistroEvidencia:
        """
        Registra evidência de aceite/confirmação de documento

        Args:
            documento_id: ID do documento
            usuario: Dados do usuário que aceitou
            aceite: True se aceitou, False se rejeitou
            observacoes: Observações adicionais

        Returns:
            RegistroEvidencia
        """
        dados = {
            "documento_id": documento_id,
            "usuario": usuario,
            "aceite": aceite,
            "observacoes": observacoes,
        }

        acao = "aceito" if aceite else "rejeitado"
        return self.registrar_evidencia(
            tipo="aceite",
            descricao=f"Documento {acao} pelo usuário {usuario.get('nome', 'N/A')}",
            dados=dados,
        )

    def buscar_evidencias(
        self,
        tipo: Optional[str] = None,
        data_inicio: Optional[datetime] = None,
        data_fim: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Busca evidências no log

        Args:
            tipo: Filtrar por tipo de evidência
            data_inicio: Data inicial (inclusive)
            data_fim: Data final (inclusive)

        Returns:
            Lista de evidências encontradas
        """
        evidencias: List[Dict] = []

        # If memory-only mode, read from memory store
        if getattr(self.config, "memory_only", False):
            with self._write_lock:
                items = list(self._memory_store)
            for ev_obj in items:
                ev = ev_obj.to_dict()
                if tipo and ev.get("tipo") != tipo:
                    continue
                ts = datetime.fromisoformat(ev.get("timestamp"))
                if data_inicio and ts < data_inicio:
                    continue
                if data_fim and ts > data_fim:
                    continue
                evidencias.append(ev)
            return evidencias

        # Otherwise read from file
        try:
            with open(self.arquivo_log, "r", encoding="utf-8") as f:
                buffer_lines = []
                for raw in f:
                    linha = raw.rstrip("\n")
                    # skip comments and blank lines when not buffering
                    if not buffer_lines and (linha.strip().startswith("#") or not linha.strip()):
                        continue

                    # Start collecting if current line looks like JSON start or we already buffering
                    if not buffer_lines and linha.strip().startswith("{"):
                        buffer_lines.append(linha)
                        continue

                    if buffer_lines:
                        buffer_lines.append(linha)
                        # Try to parse the buffered block as JSON; if ok, process and reset buffer
                        try:
                            candidate = "\n".join(buffer_lines)
                            evidencia = json.loads(candidate)

                            # Pula cabeçalho inicial
                            if (
                                "sistema" in evidencia
                                and "Sistema de Evidências" in evidencia.get("sistema", "")
                            ):
                                buffer_lines = []
                                continue

                            # Filtros
                            if tipo and evidencia.get("tipo") != tipo:
                                buffer_lines = []
                                continue

                            timestamp_evidencia = datetime.fromisoformat(
                                evidencia.get("timestamp", "")
                            )

                            if data_inicio and timestamp_evidencia < data_inicio:
                                buffer_lines = []
                                continue

                            if data_fim and timestamp_evidencia > data_fim:
                                buffer_lines = []
                                continue

                            evidencias.append(evidencia)
                            buffer_lines = []
                        except json.JSONDecodeError:
                            # Not yet a complete JSON object; continue accumulating
                            # Cap the buffer to avoid runaway memory usage
                            if len(buffer_lines) > 2000:
                                logger.warning(
                                    "Buffer overflow when parsing evidências; discarding block starting: %s",
                                    (buffer_lines[0][:80] if buffer_lines else "<empty>"),
                                )
                                buffer_lines = []
                            continue
                    else:
                        # Line doesn't start JSON and we're not buffering: warn and skip
                        if linha.strip():
                            logger.warning("Linha inválida no log: %s...", linha[:80])
                        continue
        except Exception:
            logger.exception("Falha ao ler arquivo de evidências %s", self.arquivo_log)

        return evidencias

    def verificar_integridade(self, id_evidencia: str) -> Dict:
        """
        Verifica integridade de uma evidência através do hash

        Args:
            id_evidencia: ID da evidência a verificar

        Returns:
            Dict com resultado da verificação
        """
        evidencias = self.buscar_evidencias()

        for ev in evidencias:
            if ev.get("id_evidencia") == id_evidencia:
                # Recalcula hash dos dados
                dados_json = json.dumps(
                    ev.get("dados", {}), sort_keys=True, default=str
                )
                hash_calculado = hashlib.sha256(dados_json.encode("utf-8")).hexdigest()
                hash_registrado = ev.get("hash_dados")

                integro = hash_calculado == hash_registrado

                resultado = {
                    "id_evidencia": id_evidencia,
                    "integro": integro,
                    "hash_registrado": hash_registrado,
                    "hash_calculado": hash_calculado,
                    "timestamp": ev.get("timestamp"),
                    "tipo": ev.get("tipo"),
                }

                # Verifica arquivo se existir
                arquivo = ev.get("arquivo_relacionado")
                if arquivo and Path(arquivo).exists():
                    hash_arquivo_atual = self._calcular_hash_arquivo_verificacao(
                        arquivo
                    )
                    hash_arquivo_registrado = ev.get("hash_arquivo")
                    arquivo_integro = hash_arquivo_atual == hash_arquivo_registrado

                    resultado["arquivo_relacionado"] = arquivo
                    resultado["arquivo_integro"] = arquivo_integro
                    resultado["hash_arquivo_registrado"] = hash_arquivo_registrado
                    resultado["hash_arquivo_atual"] = hash_arquivo_atual

                return resultado

        return {"id_evidencia": id_evidencia, "encontrado": False}

    def _calcular_hash_arquivo_verificacao(self, caminho_arquivo: str) -> str:
        """Calcula hash SHA-256 de um arquivo para verificação"""
        sha256_hash = hashlib.sha256()
        with open(caminho_arquivo, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def gerar_relatorio_auditoria(
        self,
        data_inicio: Optional[datetime] = None,
        data_fim: Optional[datetime] = None,
        caminho_saida: Optional[str] = None,
    ) -> str:
        """
        Gera relatório de auditoria

        Args:
            data_inicio: Data inicial do relatório
            data_fim: Data final do relatório
            caminho_saida: Caminho do arquivo de relatório (opcional)

        Returns:
            Caminho do relatório gerado
        """
        evidencias = self.buscar_evidencias(data_inicio=data_inicio, data_fim=data_fim)

        # Estatísticas
        total_evidencias = len(evidencias)
        por_tipo = {}
        for ev in evidencias:
            tipo = ev.get("tipo", "desconhecido")
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

        # Monta relatório
        relatorio = {
            "titulo": "Relatório de Auditoria - Evidências Legais",
            "periodo": {
                "inicio": (
                    data_inicio.isoformat() if data_inicio else "Início dos registros"
                ),
                "fim": data_fim.isoformat() if data_fim else "Até o momento",
            },
            "gerado_em": datetime.now().isoformat(),
            "estatisticas": {
                "total_evidencias": total_evidencias,
                "por_tipo": por_tipo,
            },
            "evidencias": evidencias,
        }

        # Salva relatório
        if caminho_saida is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if getattr(self.config, "memory_only", False):
                caminho_saida = (
                    Path(tempfile.gettempdir())
                    / f"relatorio_auditoria_{timestamp}.json"
                )
            else:
                caminho_saida = (
                    self.arquivo_log.parent / f"relatorio_auditoria_{timestamp}.json"
                )

        with open(caminho_saida, "w", encoding="utf-8") as f:
            json.dump(relatorio, f, indent=2, ensure_ascii=False)

        logger.info(f"Relatório de auditoria gerado: {caminho_saida}")
        logger.info(f"Total de evidências: {total_evidencias}")

        return str(caminho_saida)


class CadeiaEvidencias:
    """Cadeia de custódia de evidências (blockchain-like para documentos)"""

    def __init__(self, gerenciador: GerenciadorEvidencias):
        """
        Inicializa cadeia de evidências

        Args:
            gerenciador: Gerenciador de evidências
        """
        self.gerenciador = gerenciador
        self.cadeia: List[Dict] = []

    def adicionar_elo(
        self, tipo: str, dados: Dict, arquivo: Optional[str] = None
    ) -> Dict:
        """
        Adiciona novo elo na cadeia de evidências

        Args:
            tipo: Tipo da evidência
            dados: Dados do elo
            arquivo: Arquivo relacionado

        Returns:
            Dict com o elo criado
        """
        # Hash do elo anterior (ou genesis)
        hash_anterior = self.cadeia[-1]["hash_elo"] if self.cadeia else "genesis"

        # Registra evidência
        evidencia = self.gerenciador.registrar_evidencia(
            tipo, f"Elo da cadeia: {tipo}", dados, arquivo
        )

        # Cria elo
        elo = {
            "indice": len(self.cadeia),
            "timestamp": evidencia.timestamp_iso,
            "tipo": tipo,
            "hash_anterior": hash_anterior,
            "hash_dados": evidencia.hash_dados,
            "hash_arquivo": evidencia.hash_arquivo,
            "id_evidencia": evidencia.id_evidencia,
        }

        # Hash do elo completo
        elo_json = json.dumps(elo, sort_keys=True)
        elo["hash_elo"] = hashlib.sha256(elo_json.encode("utf-8")).hexdigest()

        self.cadeia.append(elo)

        logger.info(
            f"Elo adicionado à cadeia - Índice: {elo['indice']}, Hash: {elo['hash_elo'][:16]}..."
        )

        return elo

    def validar_cadeia(self) -> bool:
        """
        Valida integridade da cadeia completa

        Returns:
            True se cadeia é válida, False caso contrário
        """
        for i in range(1, len(self.cadeia)):
            elo_atual = self.cadeia[i]
            elo_anterior = self.cadeia[i - 1]

            # Verifica link com elo anterior
            if elo_atual["hash_anterior"] != elo_anterior["hash_elo"]:
                logger.error(f"Cadeia inválida no elo {i}: hash anterior não confere")
                return False

            # Recalcula hash do elo atual
            elo_temp = {k: v for k, v in elo_atual.items() if k != "hash_elo"}
            elo_json = json.dumps(elo_temp, sort_keys=True)
            hash_calculado = hashlib.sha256(elo_json.encode("utf-8")).hexdigest()

            if hash_calculado != elo_atual["hash_elo"]:
                logger.error(f"Cadeia inválida no elo {i}: hash do elo foi adulterado")
                return False

        logger.info(f"Cadeia válida - {len(self.cadeia)} elos verificados")
        return True


# Funções auxiliares de uso rápido


def registrar_evidencia_rapida(
    tipo: str, descricao: str, dados: Dict, arquivo: Optional[str] = None
) -> RegistroEvidencia:
    """
    Função rápida para registrar evidência

    Args:
        tipo: Tipo da evidência
        descricao: Descrição
        dados: Dados
        arquivo: Arquivo relacionado

    Returns:
        RegistroEvidencia
    """
    gerenciador = GerenciadorEvidencias()
    return gerenciador.registrar_evidencia(tipo, descricao, dados, arquivo)


def verificar_integridade_rapida(id_evidencia: str) -> Dict:
    """
    Função rápida para verificar integridade

    Args:
        id_evidencia: ID da evidência

    Returns:
        Dict com resultado da verificação
    """
    gerenciador = GerenciadorEvidencias()
    return gerenciador.verificar_integridade(id_evidencia)
