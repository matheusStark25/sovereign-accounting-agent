"""Cliente do HashiCorp Vault (KV v2) com token ou AppRole.

* Falha de verdade: se o Vault não responde, ``SegredoIndisponivel`` é levantada. Não existe retorno
  silencioso de ``None`` nem dicionário em memória escondido no caminho de produção.
* Cache curto em memória (padrão 60 s) para não bater no Vault a cada requisição.
* AppRole: faz login ao iniciar e renova o token antes de vencer; se o token expirar, refaz o login.
* O backend em memória (``VaultClient.em_memoria``) existe para testes e desenvolvimento e só é
  criado por chamada explícita.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Mapping, Optional

try:
    import hvac
    from hvac.exceptions import Forbidden, InvalidPath, VaultError
except Exception:  # pragma: no cover - hvac é dependência obrigatória, mas o import não pode derrubar o módulo
    hvac = None  # type: ignore
    Forbidden = InvalidPath = VaultError = Exception  # type: ignore

logger = logging.getLogger(__name__)

SEGREDOS_CONHECIDOS = (
    "JWT_SECRET", "AUDIT_HMAC_KEY", "PII_HASH_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "ADMIN_PASSWORD",
    "RPA_PQC_PUBLIC_KEY", "RPA_PQC_PRIVATE_KEY", "GOVERNANCA_DSA_KEY",
)


class SegredoIndisponivel(RuntimeError):
    """O segredo não pôde ser lido do Vault (sem conexão, sem permissão, caminho ou chave inexistente)."""


class _Memoria:
    """Backend de teste/desenvolvimento com a mesma interface mínima."""

    def __init__(self, dados: Mapping[str, Mapping[str, Any]]):
        self._dados = {k: dict(v) for k, v in dados.items()}

    def ler(self, path: str) -> Dict[str, Any]:
        if path not in self._dados:
            raise SegredoIndisponivel(f"Caminho inexistente: {path}")
        return dict(self._dados[path])

    def gravar(self, path: str, dados: Mapping[str, Any]) -> None:
        self._dados[path] = dict(dados)

    def saudavel(self) -> bool:
        return True


class VaultClient:
    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        role_id: Optional[str] = None,
        secret_id: Optional[str] = None,
        mount: str = "secret",
        namespace: Optional[str] = None,
        cache_ttl: float = 60.0,
        verify: Any = True,
        cert: Optional[tuple] = None,
        cliente: Any = None,
        _memoria: Optional[_Memoria] = None,
    ):
        self.mount, self.cache_ttl = mount, cache_ttl
        self._memoria = _memoria
        self._lock = threading.Lock()
        self._cache: Dict[str, tuple] = {}
        self._role_id, self._secret_id = role_id, secret_id
        self._expira_token: Optional[float] = None
        if _memoria is not None:
            self._client = None
            return
        if hvac is None and cliente is None:
            raise SegredoIndisponivel("A biblioteca hvac não está instalada.")
        if not url and cliente is None:
            raise SegredoIndisponivel("VAULT_ADDR não configurado.")
        self._client = cliente or hvac.Client(url=url, token=token, namespace=namespace, verify=verify, cert=cert, timeout=10)
        if not token and role_id and secret_id:
            self._login_approle()
        elif not token and cliente is None:
            raise SegredoIndisponivel("Informe VAULT_TOKEN ou VAULT_ROLE_ID e VAULT_SECRET_ID.")

    # ------------------------------------------------------------------ criação
    @classmethod
    def em_memoria(cls, dados: Mapping[str, Mapping[str, Any]]) -> "VaultClient":
        return cls(_memoria=_Memoria(dados))

    @classmethod
    def do_ambiente(cls, env: Optional[Mapping[str, str]] = None) -> Optional["VaultClient"]:
        """Cliente configurado por ``VAULT_ADDR`` + (``VAULT_TOKEN`` | ``VAULT_ROLE_ID``/``VAULT_SECRET_ID``).
        Devolve ``None`` se ``VAULT_ADDR`` não estiver definido (Vault não configurado)."""
        env = os.environ if env is None else env
        url = env.get("VAULT_ADDR") or env.get("VAULT_URL")
        if not url:
            return None
        cert = (env["VAULT_CLIENT_CERT"], env["VAULT_CLIENT_KEY"]) if env.get("VAULT_CLIENT_CERT") and env.get("VAULT_CLIENT_KEY") else None
        return cls(
            url=url, token=env.get("VAULT_TOKEN"), role_id=env.get("VAULT_ROLE_ID"), secret_id=env.get("VAULT_SECRET_ID"),
            mount=env.get("VAULT_MOUNT", "secret"), namespace=env.get("VAULT_NAMESPACE"),
            verify=env.get("VAULT_CACERT") or True, cert=cert,
        )

    # ---------------------------------------------------------------- autenticação
    def _login_approle(self) -> None:
        try:
            r = self._client.auth.approle.login(role_id=self._role_id, secret_id=self._secret_id)
        except Exception as exc:
            raise SegredoIndisponivel(f"Login AppRole falhou: {type(exc).__name__}") from exc
        auth = r.get("auth") or {}
        self._client.token = auth.get("client_token")
        self._expira_token = time.monotonic() + float(auth.get("lease_duration") or 0) if auth.get("lease_duration") else None

    def _garantir_token(self) -> None:
        """Renova o login AppRole quando falta menos de 20% do tempo do token."""
        if self._expira_token is not None and self._role_id and time.monotonic() > self._expira_token - 30:
            self._login_approle()

    # -------------------------------------------------------------------- leitura
    def _ler_bruto(self, path: str) -> Dict[str, Any]:
        if self._memoria is not None:
            return self._memoria.ler(path)
        self._garantir_token()
        try:
            r = self._client.secrets.kv.v2.read_secret_version(path=path, mount_point=self.mount, raise_on_deleted_version=True)
            return dict(r["data"]["data"])
        except InvalidPath as exc:
            raise SegredoIndisponivel(f"Caminho inexistente no Vault: {path}") from exc
        except Forbidden as exc:
            raise SegredoIndisponivel(f"Sem permissão para ler {path} no Vault.") from exc
        except Exception as exc:  # noqa: BLE001 - rede, TLS, Vault selado, resposta inesperada
            raise SegredoIndisponivel(f"Vault indisponível ({type(exc).__name__}).") from exc

    def ler(self, path: str) -> Dict[str, Any]:
        with self._lock:
            hit = self._cache.get(path)
            if hit and time.monotonic() - hit[0] < self.cache_ttl:
                return dict(hit[1])
        dados = self._ler_bruto(path)
        with self._lock:
            self._cache[path] = (time.monotonic(), dados)
        return dict(dados)

    def get_secret(self, path: str, key: str, default: Any = None) -> Any:
        """Um campo do segredo. ``default`` só vale se o caminho existe e o campo não; falha de Vault sempre levanta."""
        return self.ler(path).get(key, default)

    def get_certificate(self, path: str, key: str) -> str:
        valor = self.get_secret(path, key)
        if not valor:
            raise SegredoIndisponivel(f"Certificado {key} não encontrado em {path}.")
        return valor

    def get_private_key(self, path: str, key: str) -> str:
        valor = self.get_secret(path, key)
        if not valor:
            raise SegredoIndisponivel(f"Chave privada {key} não encontrada em {path}.")
        return valor

    def gravar(self, path: str, dados: Mapping[str, Any]) -> None:
        if self._memoria is not None:
            self._memoria.gravar(path, dados)
        else:
            self._garantir_token()
            try:
                self._client.secrets.kv.v2.create_or_update_secret(path=path, secret=dict(dados), mount_point=self.mount)
            except Exception as exc:  # noqa: BLE001
                raise SegredoIndisponivel(f"Não consegui gravar {path} no Vault ({type(exc).__name__}).") from exc
        with self._lock:
            self._cache.pop(path, None)

    def limpar_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def health(self) -> bool:
        return self.saudavel()

    def saudavel(self) -> bool:
        if self._memoria is not None:
            return self._memoria.saudavel()
        try:
            h = self._client.sys.read_health_status(method="GET")
            return bool(h.get("initialized", True)) and not h.get("sealed", False) if isinstance(h, dict) else getattr(h, "status_code", 500) == 200
        except Exception:  # noqa: BLE001
            return False


def carregar_segredos(vault: Optional[VaultClient], env: Optional[Mapping[str, str]] = None, path: Optional[str] = None) -> Dict[str, str]:
    """Ambiente com os segredos do Vault por cima das variáveis de ambiente (o Vault manda).

    Os campos ficam em ``<mount>/<VAULT_SECRET_PATH>`` (padrão ``agente``) com o nome do segredo em minúsculas
    (``jwt_secret``, ``audit_hmac_key``...). Se o Vault estiver configurado e falhar, levanta.
    """
    base = dict(os.environ if env is None else env)
    if vault is None:
        return base
    caminho = path or base.get("VAULT_SECRET_PATH", "agente")
    dados = vault.ler(caminho)
    for nome in SEGREDOS_CONHECIDOS:
        valor = dados.get(nome.lower())
        if valor:
            base[nome] = str(valor)
    return base
