esocial_baixa_tool (V3) - Quick README

Overview

- Core scaffold for mass employee offboarding with checkpoints, circuit breaker,
  adaptive Selenium handling, deep-hash caching, PDF validation hooks and chaos-mode.

Quick start

1. Install optional dependencies for full feature set (recommended in virtualenv):

```powershell
pip install selenium pdfplumber pydantic aiohttp aioredis prometheus_client psutil pika hvac
```

1. Run unit tests (these do not require Selenium):

```bash
pytest -q
```

Environment variables (important)

- `ESOCIAL_CHECKPOINT_DB` — path to sqlite checkpoint DB (default: esocial_checkpoints.db)
- `ESOCIAL_CACHE_DIR` — directory for deep-hash cache (default: .esocial_cache)
- `ESOCIAL_COOKIES_DIR` — where cookies are stored (default .esocial_cookies)
- `CERT_PASSWORD` — (sensitive) certificate password (never logged)
- `ESOCIAL_CONCURRENCY` — concurrency limit (default 10)
- `CHAOS` — set to `1` to enable chaos dry-run injection
- `SECRET_PROVIDER` — `mock` (default) or `vault`. Selects secrets provider implementation.
- `RABBIT_URL` — RabbitMQ URL, ex: `amqp://guest:guest@localhost:5672/`
- `USE_RABBIT` — `1` to publish tasks to RabbitMQ instead of executing locally
- `LOCAL_TASK_QUEUE_FILE` — path for local jsonl queue fallback (default: local_task_queue.jsonl)
- `RABBIT_FAKE` — `1` forces file-fallback consumer even if Rabbit not present

Security note: do NOT store plain-text secrets in the repo or in .env files committed to source control.
Use `SECRET_PROVIDER=vault` in production pointed at a secure Vault sidecar/service.

Providers (Sidecar / Provider pattern)

The code uses a provider factory at `contabil_agente/security/provider.py` to select a
secrets provider. This follows the Sidecar/Provider pattern so the Tool code does not need
to change if you swap Vault for another secret manager.

- `vault`: uses `contabil_agente.security.vault_provider.VaultProvider` which wraps the
  in-repo `VaultManager` (or an hvac-backed client). Configure Vault in your environment.
- `mock`: simple fallback that reads environment variables (for local/dev only).

Queue (RabbitMQ) and fallback

The publisher is in `contabil_agente/queue/rabbit_provider.py` and the worker daemon in
`contabil_agente/tools/worker_daemon.py`.

Modes:

- Producer: `executor_motor.py` will publish tasks to queue `esocial_tasks` when `USE_RABBIT=1`.
- Consumer: `worker_daemon.py` will consume RabbitMQ (requires `pika`) or read the
  `LOCAL_TASK_QUEUE_FILE` JSONL fallback when Rabbit is not available.

Examples (CMD / PowerShell):

Publish demo task:
```cmd
set USE_RABBIT=1
set RABBIT_URL=amqp://guest:guest@localhost:5672/
python contabil_agente/tools/executor_motor.py
```

Run worker (local-file fallback):
```cmd
set LOCAL_TASK_QUEUE_FILE=local_task_queue.jsonl
python contabil_agente/tools/worker_daemon.py
```

Run worker (RabbitMQ with pika):
```cmd
set RABBIT_URL=amqp://guest:guest@localhost:5672/
python contabil_agente/tools/worker_daemon.py
```

Sanitization & logs

- The repository includes `contabil_agente/services/telemetry_sanitizer.py` that
  redacts project-root paths to `[ROOT]` and compacts stacks. Keep it as the
  authoritative sanitizer — new modules log via the project loggers so sanitizer
  can process telemetry centrally.

Next recommended tasks

- Add unit tests for `provider`, `rabbit_provider` and `worker_daemon` (mocked).
- Implement a proper `hvac`-based Vault client configuration for `VaultProvider`.
- Optional: convert worker to async with `aio_pika` for better integration with other
  async components.

If you want, I can add the unit tests now (mocks) and a short helm/K8s sidecar example
for Vault integration.
