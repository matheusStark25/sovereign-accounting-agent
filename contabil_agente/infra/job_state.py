"""
Gerenciador de Estado de Jobs - Redis/Memory
Rastreia estado de jobs assíncronos (PENDING, PROCESSING, SUCCESS, FAILED)

Funcionalidades:
- Rastreamento de estado em tempo real
- TTL automático para limpeza
- Histórico de progresso
- Webhooks de notificação
- Fallback para memória quando Redis indisponível
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

try:
    import redis  # type: ignore

    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class JobStatus:
    """Estados possíveis de um job"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


class JobStateManager:
    """
    Gerencia estado de jobs no Redis (com fallback para memória)

    Estrutura de dados:
    - job:{task_id}:state -> JSON com estado completo
    - job:{task_id}:progress -> Lista de eventos de progresso
    - job:{task_id}:logs -> Lista de logs da execução
    """

    # Armazenamento em memória (fallback)
    _memory_store: Dict[str, Dict] = {}
    _memory_progress: Dict[str, List] = {}
    _memory_logs: Dict[str, List] = {}

    def __init__(self):
        # Default para localhost (desenvolvimento) - em Docker usar REDIS_URL=redis://agente_contabil_redis:6379/0
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = None
        self.use_redis = False
        self.ttl = 86400  # 24 horas

        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                # Testar conexão
                self.redis_client.ping()
                self.use_redis = True
                logger.info("JobStateManager: Usando Redis")
            except Exception as e:
                logger.warning(
                    f"JobStateManager: Redis indisponível ({e}), usando memória"
                )
                self.use_redis = False
        else:
            logger.warning(
                "JobStateManager: Pacote redis não instalado, usando memória"
            )

    def create_job(
        self,
        task_id: str,
        task_name: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Cria novo job no Redis

        Args:
            task_id: ID único do job (gerado pelo Celery)
            task_name: Nome da task
            user_id: ID do usuário que iniciou
            metadata: Metadados adicionais

        Returns:
            Estado inicial do job
        """
        state = {
            "task_id": task_id,
            "task_name": task_name,
            "status": JobStatus.PENDING,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": metadata or {},
            "progress": 0,
            "message": "Job criado, aguardando processamento",
        }

        # Salva estado (Redis ou memória)
        if self.use_redis and self.redis_client:
            self.redis_client.setex(
                f"job:{task_id}:state",
                self.ttl,
                json.dumps(state),
            )
        else:
            JobStateManager._memory_store[f"job:{task_id}:state"] = state

        logger.info(f"Job criado: {task_id} ({task_name})")
        return state

    def update_state(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Atualiza estado do job

        Args:
            task_id: ID do job
            status: Novo status (PENDING, PROCESSING, etc.)
            progress: Progresso percentual (0-100)
            message: Mensagem descritiva
            metadata: Metadados adicionais

        Returns:
            Estado atualizado
        """
        # Recupera estado atual
        current_state = self.get_state(task_id)
        if not current_state:
            logger.warning(f"Job {task_id} não encontrado, criando novo estado")
            current_state = {
                "task_id": task_id,
                "status": JobStatus.PENDING,
                "created_at": datetime.now().isoformat(),
            }

        # Atualiza campos
        if status:
            current_state["status"] = status
        if progress is not None:
            current_state["progress"] = progress
        if message:
            current_state["message"] = message
        if metadata:
            current_state.setdefault("metadata", {}).update(metadata)

        current_state["updated_at"] = datetime.now().isoformat()

        # Salva (Redis ou memória)
        if self.use_redis and self.redis_client:
            self.redis_client.setex(
                f"job:{task_id}:state",
                self.ttl,
                json.dumps(current_state),
            )
        else:
            JobStateManager._memory_store[f"job:{task_id}:state"] = current_state

        # Adiciona evento de progresso
        self._add_progress_event(
            task_id,
            status=status or current_state.get("status"),
            progress=progress,
            message=message,
        )

        return current_state

    def get_state(self, task_id: str) -> Optional[Dict]:
        """Retorna estado atual do job"""
        if self.use_redis and self.redis_client:
            state_json = self.redis_client.get(f"job:{task_id}:state")
            if not state_json:
                return None
            try:
                return json.loads(state_json)
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar estado do job {task_id}: {e}")
                return None
        else:
            return JobStateManager._memory_store.get(f"job:{task_id}:state")

    def _add_progress_event(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        """Adiciona evento de progresso ao histórico"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "progress": progress,
            "message": message,
        }

        key = f"job:{task_id}:progress"
        if self.use_redis and self.redis_client:
            # Adiciona à lista de progresso (mantém últimos 100 eventos)
            self.redis_client.lpush(key, json.dumps(event))
            self.redis_client.ltrim(key, 0, 99)
            self.redis_client.expire(key, self.ttl)
        else:
            if key not in JobStateManager._memory_progress:
                JobStateManager._memory_progress[key] = []
            JobStateManager._memory_progress[key].insert(0, event)
            JobStateManager._memory_progress[key] = JobStateManager._memory_progress[
                key
            ][:100]

    def get_progress_history(self, task_id: str) -> List[Dict]:
        """Retorna histórico de progresso do job"""
        key = f"job:{task_id}:progress"
        if self.use_redis and self.redis_client:
            events = self.redis_client.lrange(key, 0, -1)
            return [json.loads(event) for event in events]
        else:
            return JobStateManager._memory_progress.get(key, [])

    def add_log(self, task_id: str, level: str, message: str) -> None:
        """Adiciona log ao job"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }

        key = f"job:{task_id}:logs"
        if self.use_redis and self.redis_client:
            self.redis_client.lpush(key, json.dumps(log_entry))
            self.redis_client.ltrim(key, 0, 499)  # Mantém últimos 500
            self.redis_client.expire(key, self.ttl)
        else:
            if key not in JobStateManager._memory_logs:
                JobStateManager._memory_logs[key] = []
            JobStateManager._memory_logs[key].insert(0, log_entry)
            JobStateManager._memory_logs[key] = JobStateManager._memory_logs[key][:500]

    def get_logs(self, task_id: str) -> List[Dict]:
        """Retorna logs do job"""
        key = f"job:{task_id}:logs"
        if self.use_redis and self.redis_client:
            logs = self.redis_client.lrange(key, 0, -1)
            return [json.loads(log) for log in logs]
        else:
            return JobStateManager._memory_logs.get(key, [])

    def list_jobs(
        self, status_filter: Optional[str] = None, limit: int = 50
    ) -> List[Dict]:
        """Lista jobs, opcionalmente filtrados por status"""
        jobs = []

        if self.use_redis and self.redis_client:
            for key in self.redis_client.scan_iter("job:*:state", count=limit):
                state_json = self.redis_client.get(key)
                if state_json:
                    state = json.loads(state_json)
                    if status_filter and state.get("status") != status_filter:
                        continue
                    jobs.append(state)
                    if len(jobs) >= limit:
                        break
        else:
            for key, state in JobStateManager._memory_store.items():
                if key.endswith(":state"):
                    if status_filter and state.get("status") != status_filter:
                        continue
                    jobs.append(state)
                    if len(jobs) >= limit:
                        break

        return jobs

    def cancel_job(self, task_id: str) -> bool:
        """
        Marca job como cancelado
        Nota: não mata o processo em execução, apenas marca como cancelado
        """
        state = self.get_state(task_id)
        if not state:
            return False

        # Só pode cancelar se ainda não terminou
        if state["status"] in [JobStatus.SUCCESS, JobStatus.FAILED]:
            return False

        self.update_state(
            task_id,
            status=JobStatus.CANCELLED,
            message="Job cancelado pelo usuário",
        )

        logger.info(f"Job cancelado: {task_id}")
        return True

    def cleanup_old_jobs(self, days: int = 7) -> int:
        """
        Remove jobs antigos

        Args:
            days: Remove jobs mais antigos que X dias

        Returns:
            Número de jobs removidos
        """
        cutoff = datetime.now() - timedelta(days=days)
        removed = 0

        if self.use_redis and self.redis_client:
            # Busca todas as chaves de job no Redis
            for key in self.redis_client.scan_iter("job:*:state"):
                state_json = self.redis_client.get(key)
                if not state_json:
                    continue

                try:
                    state = json.loads(state_json)
                    created_at = datetime.fromisoformat(state["created_at"])

                    if created_at < cutoff:
                        task_id = state["task_id"]

                        # Remove todas as chaves relacionadas
                        self.redis_client.delete(f"job:{task_id}:state")
                        self.redis_client.delete(f"job:{task_id}:progress")
                        self.redis_client.delete(f"job:{task_id}:logs")

                        removed += 1
                except Exception as e:
                    logger.error(f"Erro ao limpar job {key}: {e}")
        else:
            # Limpar da memória
            keys_to_remove = []
            for key, state in JobStateManager._memory_store.items():
                if key.endswith(":state"):
                    try:
                        created_at = datetime.fromisoformat(state.get("created_at", ""))
                        if created_at < cutoff:
                            task_id = state.get("task_id")
                            keys_to_remove.append(task_id)
                            removed += 1
                    except Exception:
                        pass

            for task_id in keys_to_remove:
                JobStateManager._memory_store.pop(f"job:{task_id}:state", None)
                JobStateManager._memory_progress.pop(f"job:{task_id}:progress", None)
                JobStateManager._memory_logs.pop(f"job:{task_id}:logs", None)

        logger.info(f"Limpeza concluída: {removed} jobs removidos")
        return removed
