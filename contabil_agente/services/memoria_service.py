from collections import deque
import logging
import threading
from typing import Deque, Tuple

from config.settings import MEMORIA_LIMIT

logger = logging.getLogger(__name__)


class MemoryCacheService:
    """Singleton service that stores recent QA pairs in memory.

    - Uses a deque with a fixed maxlen to enforce FIFO eviction.
    - Thread-safe: methods protect access with a lock.
    - Provides auditing logs on read/write operations.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryCacheService, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # initialize only once
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._memoria: Deque[Tuple[str, str, str]] = deque(maxlen=MEMORIA_LIMIT)
        self._lock = threading.Lock()
        self._initialized = True

    def atualizar_memoria(self, cnpj: str, pergunta: str, resposta: str) -> None:
        """Adiciona um triplet (cnpj, pergunta, resposta) na memória.

        Thread-safe. Logs auditoria informando o CNPJ e o novo tamanho.
        """
        with self._lock:
            self._memoria.append((cnpj, pergunta, resposta))
            logger.info(
                "Memória atualizada: cnpj=%s, total_entries=%d",
                cnpj,
                len(self._memoria),
            )

    def recuperar_memoria(self, cnpj: str) -> str:
        """Recupera todas as respostas armazenadas para um CNPJ (FIFO order).

        Thread-safe. Retorna uma string com cada resposta separada por newline,
        compatível com a API anterior.
        """
        with self._lock:
            respostas = [entry[2] for entry in self._memoria if entry[0] == cnpj]
            logger.info(
                "Memória recuperada: cnpj=%s, entries_returned=%d",
                cnpj,
                len(respostas),
            )
            return "\n".join(respostas)

    def sincronizar_com_db(self, prefix_session_id: str = "memcache:") -> int:
        """Sincroniza o estado atual do cache com o `SessionService` persistente.

        - Agrupa entradas por CNPJ e cria/atualiza sessões no `SessionService`.
        - `prefix_session_id` evita colisões com session_ids existentes.

        Retorna o número de sessões sincronizadas.
        """
        try:
            # Import local para evitar import cycles
            from contabil_agente.services.session_service import session_service
        except Exception as e:
            logger.error(
                "sincronizar_com_db: não foi possível importar SessionService: %s", e
            )
            return 0

        # Agrupa por CNPJ
        agrupado = {}
        with self._lock:
            for cnpj, pergunta, resposta in list(self._memoria):
                agrupado.setdefault(cnpj, []).append(
                    {"role": "assistant", "content": resposta}
                )

        sincronizados = 0
        for cnpj, messages in agrupado.items():
            session_id = f"{prefix_session_id}{cnpj}"
            existing = session_service.get_session(session_id)
            if existing:
                # Atualiza acumulando mensagens existentes
                existing_messages = existing.get("messages", []) or []
                combined = existing_messages + messages
                session_service.update_session(session_id, messages=combined)
            else:
                session_service.create_session(
                    session_id,
                    messages=messages,
                    context={"source": "memory_cache"},
                    profile="memoria",
                )
            sincronizados += 1

        logger.info("sincronizar_com_db: sincronizadas %d sessões", sincronizados)
        return sincronizados


# Expose a module-level singleton instance for easy import/use
memory_service = MemoryCacheService()


# Backwards-compatible module-level functions (mantém nomes originais)
def atualizar_memoria(cnpj: str, pergunta: str, resposta: str) -> None:
    """Compat wrapper — mantém assinatura original para orquestrador."""
    memory_service.atualizar_memoria(cnpj, pergunta, resposta)


def recuperar_memoria(cnpj: str) -> str:
    """Compat wrapper — mantém assinatura original para orquestrador."""
    return memory_service.recuperar_memoria(cnpj)
