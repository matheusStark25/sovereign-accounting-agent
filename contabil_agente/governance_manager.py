"""
Módulo de Governança: Assinatura Digital, Aprovação de Threshold e Alertas de Anomalia
Extensão do sistema sem quebrar funcionalidades existentes.
"""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _safe_decimal(v, default=Decimal("0")):
    try:
        if v is None:
            return default
        return Decimal(str(v))
    except Exception:
        return default


# ===============================
# ASSINATURA DIGITAL DE DECISÕES
# ===============================
@dataclass
class DecisaoAssinada:
    """Decisão crítica com assinatura digital e timestamp."""

    id_sessao: str
    tipo_decisao: str  # 'rescisao', 'folha_pagamento', 'calculo_especial'
    valor: Decimal
    usuario: str
    timestamp: str
    hash_conteudo: str
    assinatura_digital: str
    status_aprovacao: str = "pendente"  # pendente, aprovado, rejeitado
    motivo_rejeicao: Optional[str] = None
    data_aprovacao: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class GestorAssinaturasDigitais:
    """Gerencia assinatura e auditoria de decisões críticas."""

    def __init__(self, logs_dir: str, secret_key: str):
        self.logs_dir = logs_dir
        self.secret_key = (
            secret_key.encode() if isinstance(secret_key, str) else secret_key
        )
        self.assinaturas_path = os.path.join(logs_dir, "assinaturas_digitais.json")
        self.lock = threading.Lock()
        self._init_arquivo()

    def _init_arquivo(self):
        """Inicializa arquivo de assinaturas se não existir."""
        if not os.path.exists(self.assinaturas_path):
            with open(self.assinaturas_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def assinar_decisao(self, decisao: DecisaoAssinada) -> DecisaoAssinada:
        """Assina digitalmente uma decisão crítica."""
        try:
            # Gerar hash do conteúdo
            conteudo = (
                f"{decisao.id_sessao}:"
                f"{decisao.tipo_decisao}:"
                f"{decisao.valor}:"
                f"{decisao.usuario}:"
                f"{decisao.timestamp}"
            )
            hash_conteudo = hashlib.sha256(conteudo.encode()).hexdigest()

            # Gerar assinatura HMAC
            assinatura = hmac.new(
                self.secret_key, conteudo.encode(), hashlib.sha256
            ).hexdigest()

            decisao.hash_conteudo = hash_conteudo
            decisao.assinatura_digital = assinatura

            # Persistir
            with self.lock:
                with open(self.assinaturas_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                dados.append(asdict(decisao))

                with open(self.assinaturas_path, "w", encoding="utf-8") as f:
                    json.dump(dados, f, ensure_ascii=False, indent=2)

            logger.info(
                f"Decisão assinada digitalmente: {decisao.tipo_decisao} (Hash: {hash_conteudo[:16]}...)"
            )
            return decisao

        except Exception as e:
            logger.exception(f"Erro ao assinar decisão: {str(e)}")
            raise

    def verificar_assinatura(self, decisao: DecisaoAssinada) -> bool:
        """Verifica integridade da assinatura digital."""
        try:
            conteudo = (
                f"{decisao.id_sessao}:"
                f"{decisao.tipo_decisao}:"
                f"{decisao.valor}:"
                f"{decisao.usuario}:"
                f"{decisao.timestamp}"
            )
            assinatura_esperada = hmac.new(
                self.secret_key, conteudo.encode(), hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(decisao.assinatura_digital, assinatura_esperada)
        except Exception as e:
            logger.warning(f"Erro ao verificar assinatura: {str(e)}")
            return False

    def listar_assinaturas(self, filtro_tipo: Optional[str] = None) -> List[Dict]:
        """Lista todas as decisões assinadas com filtro opcional."""
        try:
            with self.lock:
                with open(self.assinaturas_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

            if filtro_tipo:
                dados = [d for d in dados if d.get("tipo_decisao") == filtro_tipo]

            return sorted(dados, key=lambda x: x.get("timestamp", ""), reverse=True)
        except Exception as e:
            logger.exception(f"Erro ao listar assinaturas: {str(e)}")
            return []


# ===============================
# APROVAÇÃO COM THRESHOLD
# ===============================
class GestorAprovacaoThreshold:
    """Gerencia aprovação de decisões acima de valores limites."""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir
        self.aprovacoes_path = os.path.join(logs_dir, "aprovacoes_pendentes.json")
        self.lock = threading.Lock()

        # Thresholds padrão por tipo de decisão (em Reais)
        self.thresholds = {
            "rescisao": Decimal("5000.00"),  # Acima de R$ 5k
            "folha_pagamento": Decimal("50000.00"),  # Acima de R$ 50k
            "calculo_especial": Decimal("10000.00"),
            "multa_fgts": Decimal("3000.00"),
        }
        self._init_arquivo()

    def _init_arquivo(self):
        """Inicializa arquivo de aprovações pendentes."""
        if not os.path.exists(self.aprovacoes_path):
            with open(self.aprovacoes_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def requer_aprovacao(self, tipo_decisao: str, valor: Decimal) -> bool:
        """Verifica se decisão requer aprovação acima do threshold."""
        try:
            valor_decimal = _safe_decimal(valor)
            threshold = self.thresholds.get(tipo_decisao, Decimal("100000.00"))
            return valor_decimal > threshold
        except Exception as e:
            logger.warning(f"Erro ao verificar threshold: {str(e)}")
            return False

    def criar_aprovacao_pendente(
        self,
        id_sessao: str,
        tipo_decisao: str,
        valor: Decimal,
        usuario: str,
        detalhes: Dict,
    ) -> str:
        """Cria registro de aprovação pendente e retorna ID."""
        try:
            id_aprovacao = (
                f"APR-{id_sessao[:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )

            aprovacao = {
                "id_aprovacao": id_aprovacao,
                "id_sessao": id_sessao,
                "tipo_decisao": tipo_decisao,
                "valor": str(valor),
                "usuario_solicitante": usuario,
                "timestamp_criacao": datetime.now().isoformat(),
                "status": "pendente",
                "detalhes": detalhes,
                "usuario_aprovador": None,
                "timestamp_aprovacao": None,
                "motivo": None,
            }

            with self.lock:
                with open(self.aprovacoes_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                dados.append(aprovacao)

                with open(self.aprovacoes_path, "w", encoding="utf-8") as f:
                    json.dump(dados, f, ensure_ascii=False, indent=2)

            logger.info(
                f"Aprovação pendente criada: {id_aprovacao} (Tipo: {tipo_decisao}, Valor: R$ {valor})"
            )
            return id_aprovacao

        except Exception as e:
            logger.exception(f"Erro ao criar aprovação pendente: {str(e)}")
            raise

    def aprovar_decisao(
        self, id_aprovacao: str, usuario_aprovador: str, motivo: str = ""
    ) -> bool:
        """Aprova uma decisão pendente."""
        try:
            with self.lock:
                with open(self.aprovacoes_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                for item in dados:
                    if item["id_aprovacao"] == id_aprovacao:
                        item["status"] = "aprovado"
                        item["usuario_aprovador"] = usuario_aprovador
                        item["timestamp_aprovacao"] = datetime.now().isoformat()
                        item["motivo"] = motivo

                        with open(self.aprovacoes_path, "w", encoding="utf-8") as f:
                            json.dump(dados, f, ensure_ascii=False, indent=2)

                        logger.info(
                            f"Decisão aprovada: {id_aprovacao} por {usuario_aprovador}"
                        )
                        return True

            return False
        except Exception as e:
            logger.exception(f"Erro ao aprovar decisão: {str(e)}")
            return False

    def rejeitar_decisao(
        self, id_aprovacao: str, usuario_aprovador: str, motivo: str
    ) -> bool:
        """Rejeita uma decisão pendente."""
        try:
            with self.lock:
                with open(self.aprovacoes_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                for item in dados:
                    if item["id_aprovacao"] == id_aprovacao:
                        item["status"] = "rejeitado"
                        item["usuario_aprovador"] = usuario_aprovador
                        item["timestamp_aprovacao"] = datetime.now().isoformat()
                        item["motivo"] = motivo

                        with open(self.aprovacoes_path, "w", encoding="utf-8") as f:
                            json.dump(dados, f, ensure_ascii=False, indent=2)

                        logger.warning(
                            f"Decisão rejeitada: {id_aprovacao} por {usuario_aprovador}. Motivo: {motivo}"
                        )
                        return True

            return False
        except Exception as e:
            logger.exception(f"Erro ao rejeitar decisão: {str(e)}")
            return False

    def listar_pendentes(self) -> List[Dict]:
        """Lista todas as aprovações pendentes."""
        try:
            with self.lock:
                with open(self.aprovacoes_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

            return [d for d in dados if d["status"] == "pendente"]
        except Exception as e:
            logger.exception(f"Erro ao listar pendentes: {str(e)}")
            return []


# ===============================
# DETECÇÃO DE ANOMALIAS
# ===============================
class DetectorAnomalias:
    """Detecta anomalias nas operações para alertar."""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir
        self.alertas_path = os.path.join(logs_dir, "alertas_anomalias.json")
        self.lock = threading.Lock()
        self._init_arquivo()

        # Limites para detecção de anomalia
        self.limites = {
            "valor_maximo_rescisao": Decimal("100000.00"),
            "valor_maximo_folha": Decimal("500000.00"),
            "taxa_erro_threshold": 0.3,  # 30% de erros
            "tentativas_rapidas": 10,  # 10 tentativas em 1 minuto
        }

    def _init_arquivo(self):
        """Inicializa arquivo de alertas."""
        if not os.path.exists(self.alertas_path):
            with open(self.alertas_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def detectar_valor_anomalo(
        self, tipo_decisao: str, valor: Decimal
    ) -> Tuple[bool, str]:
        """Detecta valores anômalamente altos."""
        try:
            valor_decimal = Decimal(str(valor))

            if (
                tipo_decisao == "rescisao"
                and valor_decimal > self.limites["valor_maximo_rescisao"]
            ):
                return True, f"Rescisão com valor anomalo: R$ {valor}"
            elif (
                tipo_decisao == "folha_pagamento"
                and valor_decimal > self.limites["valor_maximo_folha"]
            ):
                return True, f"Folha de pagamento com valor anômalo: R$ {valor}"

            return False, ""
        except Exception as e:
            logger.warning(f"Erro ao detectar valor anômalo: {str(e)}")
            return False, ""

    def registrar_alerta(
        self, tipo_alerta: str, severidade: str, mensagem: str, metadata: Dict = None
    ) -> str:
        """Registra um alerta de anomalia."""
        try:
            id_alerta = (
                f"ALR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"
            )

            alerta = {
                "id_alerta": id_alerta,
                "tipo": tipo_alerta,
                "severidade": severidade,  # 'baixa', 'média', 'alta', 'crítica'
                "mensagem": mensagem,
                "timestamp": datetime.now().isoformat(),
                "resolvido": False,
                "timestamp_resolucao": None,
                "metadata": metadata or {},
            }

            with self.lock:
                with open(self.alertas_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                dados.append(alerta)

                with open(self.alertas_path, "w", encoding="utf-8") as f:
                    json.dump(dados, f, ensure_ascii=False, indent=2)

            logger.warning(f"Alerta registrado ({severidade}): {mensagem}")
            return id_alerta

        except Exception as e:
            logger.exception(f"Erro ao registrar alerta: {str(e)}")
            return ""

    def marcar_alerta_resolvido(self, id_alerta: str) -> bool:
        """Marca um alerta como resolvido."""
        try:
            with self.lock:
                with open(self.alertas_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

                for item in dados:
                    if item["id_alerta"] == id_alerta:
                        item["resolvido"] = True
                        item["timestamp_resolucao"] = datetime.now().isoformat()

                        with open(self.alertas_path, "w", encoding="utf-8") as f:
                            json.dump(dados, f, ensure_ascii=False, indent=2)

                        return True

            return False
        except Exception as e:
            logger.exception(f"Erro ao marcar alerta resolvido: {str(e)}")
            return False

    def listar_alertas_ativos(self) -> List[Dict]:
        """Lista todos os alertas não resolvidos."""
        try:
            with self.lock:
                with open(self.alertas_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)

            alertas = [d for d in dados if not d["resolvido"]]
            return sorted(
                alertas,
                key=lambda x: {"crítica": 0, "alta": 1, "média": 2, "baixa": 3}.get(
                    x.get("severidade"), 4
                ),
            )
        except Exception as e:
            logger.exception(f"Erro ao listar alertas: {str(e)}")
            return []


# ===============================
# REGISTRO DE DOCUMENTOS SEGUROS
# ===============================
class DocumentRegistry:
    """Registra hashes de documentos em um banco seguro local (SQLite).

    Uso simples: registrar hash e recuperar por nome.
    """

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir
        os.makedirs(self.logs_dir, exist_ok=True)
        self.db_path = os.path.join(self.logs_dir, "documents_secure.db")
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    sha256 TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def register_hash(self, filename: str, sha256: str, metadata: Dict = None) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO documents (filename, sha256, metadata) VALUES (?, ?, ?)",
                (filename, sha256, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.commit()
            conn.close()
            logger.info(
                f"Hash registrado em documents_secure: {filename} ({sha256[:12]}...)"
            )
            return True
        except Exception as e:
            logger.exception(f"Erro ao registrar hash de documento: {str(e)}")
            return False


# ===============================
# DASHBOARD DE AUDITORIA (Dados)
# ===============================
class ProvedorDashboardAuditoria:
    """Fornece dados para dashboard de auditoria em tempo real."""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir
        self.evolucao_path = os.path.join(logs_dir, "evolucao_sistema.json")
        # Cache leve para degradação controlada
        self._cache = {
            "stats": None,
            "stats_ts": None,
            "historico": None,
            "historico_ts": None,
        }
        self.snapshot_path = os.path.join(logs_dir, "dashboard_snapshot.json")
        self._load_snapshot()

    def obter_estatisticas(self, horas: int = 24) -> Dict[str, Any]:
        """Obtém estatísticas dos últimos N horas."""
        try:
            cutoff = datetime.now() - timedelta(hours=horas)

            with open(self.evolucao_path, "r", encoding="utf-8") as f:
                dados = json.load(f)

            # Filtrar por período
            dados_filtrados = [
                d
                for d in dados
                if datetime.fromisoformat(d.get("timestamp", "")) > cutoff
            ]

            total = len(dados_filtrados)
            sucesso = sum(1 for d in dados_filtrados if d.get("status_sucesso", False))
            falha = total - sucesso

            resultado = {
                "periodo_horas": horas,
                "total_operacoes": total,
                "operacoes_sucesso": sucesso,
                "operacoes_falha": falha,
                "taxa_sucesso": (sucesso / total * 100) if total > 0 else 0,
                "timestamp_geracao": datetime.now().isoformat(),
                "degradado": False,
            }
            self._cache["stats"] = resultado
            self._cache["stats_ts"] = datetime.now().isoformat()
            self._persist_snapshot()
            return resultado
        except Exception as e:
            logger.exception(f"Erro ao obter estatísticas: {str(e)}")
            # Degradação controlada: retorna cache se existir
            if self._cache["stats"]:
                cached = dict(self._cache["stats"])
                cached["degradado"] = True
                cached["origem"] = "cache"
                return cached
            return {"degradado": True, "erro": str(e)}

    def obter_historico_resumido(self, limite: int = 50) -> List[Dict]:
        """Retorna histórico resumido das últimas operações."""
        try:
            with open(self.evolucao_path, "r", encoding="utf-8") as f:
                dados = json.load(f)

            dados_resumidos = []
            for d in sorted(dados, key=lambda x: x.get("timestamp", ""), reverse=True)[
                :limite
            ]:
                dados_resumidos.append(
                    {
                        "timestamp": d.get("timestamp"),
                        "intencao": d.get("intencao_detectada"),
                        "status": "sucesso" if d.get("status_sucesso") else "falha",
                        "tempo_ms": round(
                            d.get("tempo_processamento_seg", 0) * 1000, 0
                        ),
                    }
                )

            self._cache["historico"] = dados_resumidos
            self._cache["historico_ts"] = datetime.now().isoformat()
            self._persist_snapshot()
            return dados_resumidos
        except Exception as e:
            logger.exception(f"Erro ao obter histórico: {str(e)}")
            if self._cache["historico"]:
                return self._cache["historico"]
            return []

    def _persist_snapshot(self):
        """Persiste snapshot combinando stats e historico para degradação controlada."""
        try:
            payload = {
                "stats": self._cache.get("stats"),
                "stats_ts": self._cache.get("stats_ts"),
                "historico": self._cache.get("historico"),
                "historico_ts": self._cache.get("historico_ts"),
                "timestamp_snapshot": datetime.now().isoformat(),
            }
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Erro ao persistir snapshot do dashboard")

    def _load_snapshot(self):
        """Carrega snapshot para cache em caso de degradação inicial."""
        try:
            if not os.path.exists(self.snapshot_path):
                return

            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            self._cache["stats"] = payload.get("stats")
            self._cache["stats_ts"] = payload.get("stats_ts")
            self._cache["historico"] = payload.get("historico")
            self._cache["historico_ts"] = payload.get("historico_ts")
        except Exception:
            logger.warning("Falha ao carregar snapshot do dashboard", exc_info=True)
