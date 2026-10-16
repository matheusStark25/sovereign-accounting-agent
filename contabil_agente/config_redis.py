"""
CONFIGURAÃÃO REDIS PARA PRODUÃÃO
Adiciona cache distribuÃ­do e rate limiting escalÃ¡vel
"""

import os
import pickle
from functools import wraps
from typing import Any, Optional

import redis


class RedisManager:
    """Gerenciador centralizado de Redis para cache e rate limiting"""

    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = None
        self._connect()

    def _connect(self):
        """Conecta ao Redis com fallback"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                decode_responses=False,  # Permite armazenar bytes
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            # Testa conexÃ£o
            self.client.ping()
            print("â Redis conectado com sucesso!")
        except Exception as e:
            print(f"â ï¸ Redis nÃ£o disponÃ­vel, usando fallback em memÃ³ria: {e}")
            self.client = None

    def get(self, key: str) -> Optional[Any]:
        """Busca valor do cache"""
        if not self.client:
            return None

        try:
            value = self.client.get(key)
            if value:
                return pickle.loads(value)
            return None
        except Exception as e:
            print(f"Erro ao buscar do Redis: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = 3600):
        """Armazena valor no cache com TTL"""
        if not self.client:
            return False

        try:
            serialized = pickle.dumps(value)
            self.client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            print(f"Erro ao salvar no Redis: {e}")
            return False

    def delete(self, key: str):
        """Remove chave do cache"""
        if not self.client:
            return False

        try:
            self.client.delete(key)
            return True
        except Exception as e:
            print(f"Erro ao deletar do Redis: {e}")
            return False

    def increment(self, key: str, amount: int = 1) -> int:
        """Incrementa contador (para rate limiting)"""
        if not self.client:
            return 0

        try:
            return self.client.incr(key, amount)
        except Exception as e:
            print(f"Erro ao incrementar no Redis: {e}")
            return 0

    def expire(self, key: str, seconds: int):
        """Define TTL para uma chave"""
        if not self.client:
            return False

        try:
            self.client.expire(key, seconds)
            return True
        except Exception as e:
            print(f"Erro ao definir TTL: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Verifica se chave existe"""
        if not self.client:
            return False

        try:
            return bool(self.client.exists(key))
        except BaseException:
            return False


# Singleton global
_redis_manager = None


def get_redis_manager() -> RedisManager:
    """Retorna instÃ¢ncia singleton do RedisManager"""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager


# Decorator para cache de funÃ§Ãµes
def redis_cache(ttl: int = 3600, key_prefix: str = "cache"):
    """
    Decorator para cachear resultados de funÃ§Ãµes no Redis

    Usage:
        @redis_cache(ttl=1800, key_prefix="calculos")
        def calcular_inss(salario):
            # ... cÃ¡lculo pesado ...
            return resultado
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis_mgr = get_redis_manager()

            # Gera chave Ãºnica baseada em funÃ§Ã£o e argumentos
            key_data = f"{key_prefix}:{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            cache_key = f"cache:{hash(key_data)}"

            # Tenta buscar do cache
            cached_result = redis_mgr.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Executa funÃ§Ã£o e armazena resultado
            result = func(*args, **kwargs)
            redis_mgr.set(cache_key, result, ttl)

            return result

        return wrapper

    return decorator


# Rate Limiting customizado com Redis
class RedisRateLimiter:
    """Rate limiter usando Redis para distribuiÃ§Ã£o"""

    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager

    def is_allowed(self, identifier: str, limit: int, window: int) -> bool:
        """
        Verifica se requisiÃ§Ã£o Ã© permitida

        Args:
            identifier: Identificador Ãºnico (IP, session_id, etc)
            limit: NÃºmero mÃ¡ximo de requisiÃ§Ãµes
            window: Janela de tempo em segundos

        Returns:
            True se permitido, False se excedeu limite
        """
        key = f"ratelimit:{identifier}"

        try:
            current = self.redis.increment(key)

            if current == 1:
                # Primeira requisiÃ§Ã£o, define TTL
                self.redis.expire(key, window)

            return current <= limit
        except BaseException:
            # Fallback: permite se Redis falhar
            return True

    def get_remaining(self, identifier: str, limit: int) -> int:
        """Retorna quantas requisiÃ§Ãµes restam"""
        key = f"ratelimit:{identifier}"

        try:
            current = self.redis.client.get(key)
            if current is None:
                return limit
            return max(0, limit - int(current))
        except BaseException:
            return limit


if __name__ == "__main__":
    # Teste rÃ¡pido
    print("Testando Redis...")
    redis_mgr = get_redis_manager()

    # Teste de cache
    redis_mgr.set("test_key", {"valor": 123, "nome": "teste"}, ttl=60)
    result = redis_mgr.get("test_key")
    print(f"Teste cache: {result}")

    # Teste de rate limiting
    limiter = RedisRateLimiter(redis_mgr)
    for i in range(5):
        allowed = limiter.is_allowed("test_user", limit=3, window=60)
        print(f"RequisiÃ§Ã£o {i + 1}: {'Permitida' if allowed else 'Bloqueada'}")
