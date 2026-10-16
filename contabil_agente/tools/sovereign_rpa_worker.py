"""
Sovereign RPA Worker

Implementa um worker self-contained, idempotente e auditável para executar
um workflow de steps (ex: Sintegra/TED/SEFIP). Fornece:
- Lock híbrido baseado em Path.mkdir (Windows-safe)
- Checkpointing atômico com hash de integridade
- Idempotência forense por hashes SHA-256 consolidados
- Full-jitter retry
- Fault injection API via MockAutomationAdapter.FaultInjector
- Logs JSON Lines auditáveis

Design notes:
- Operações em modo `dry_run` não escrevem checkpoint nem artefatos em disco
- O arquivo é intencionalmente robusto a falhas silenciosas
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import random
import hashlib
import datetime
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Exceptions Hierarchy


class SovereignError(Exception):
    pass


class SovereignComplianceError(SovereignError):
    pass


class SovereignIntegrityError(SovereignError):
    pass


class SovereignHumanRejectionError(SovereignError):
    pass


# Fault Injector


class FaultInjector:
    """Simple fault injector for MockAutomationAdapter.

    set_fault(method_name, fault_type, probability) where probability in [0,1].
    Supported fault_type: 'TIMEOUT', 'SOVEREIGN_INTEGRITY', 'SLOW_RESPONSE'
    """

    def __init__(self):
        self._faults: Dict[str, Tuple[str, float]] = {}

    def set_fault(self, method_name: str, fault_type: str, probability: float):
        self._faults[method_name] = (fault_type, float(probability))

    def clear_faults(self):
        self._faults.clear()

    def maybe_inject(self, method_name: str):
        f = self._faults.get(method_name)
        if not f:
            return None
        fault_type, prob = f
        if random.random() <= prob:
            return fault_type
        return None


# Mock Automation Adapter (simula Sintegra/TED/SEFIP)


class MockAutomationAdapter:
    def __init__(
        self, injector: Optional[FaultInjector] = None, slow_base: float = 0.1
    ):
        self.injector = injector or FaultInjector()
        self.slow_base = slow_base

    def perform_step(
        self, step_id: str, expected_artifacts: List[Path]
    ) -> List[Tuple[str, bytes]]:
        """Executa o passo e retorna lista de (name, bytes) para cada artefato.

        Pode injetar falhas via FaultInjector.
        """
        # Faults
        fault = self.injector.maybe_inject("perform_step")
        if fault == "TIMEOUT":
            # Simulate no response by sleeping longer than typical timeouts
            time.sleep(5)
        elif fault == "SOVEREIGN_INTEGRITY":
            raise SovereignIntegrityError("Injected integrity fault")
        elif fault == "SLOW_RESPONSE":
            time.sleep(self.slow_base + random.random() * 0.5)

        # Special compliance failure: if step name asks to sign 'LEONEL'
        if "LEONEL" in step_id.upper():
            raise SovereignComplianceError("Assinatura LEONEL falhou")

        artifacts: List[Tuple[str, bytes]] = []
        for p in expected_artifacts:
            # In a real adapter we'd call external tool and produce files.
            # Here we synthesize deterministic content to allow for reproducible hashes.
            name = p.name
            content = (f"artifact:{step_id}:{name}").encode("utf-8")
            artifacts.append((name, content))

        return artifacts


# Audit Logger (JSON lines)


class AuditLogger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _format_exception(self, exc: Exception) -> Dict[str, Any]:
        return {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

    def log(
        self,
        level: str,
        step: str,
        duration_ms: float,
        hash_consolidado: str,
        exception: Optional[Exception] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        entry = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": level,
            "step": step,
            "duration_ms": int(duration_ms),
            "hash_consolidado": hash_consolidado,
        }
        if exception is not None:
            entry["exception"] = self._format_exception(exception)
        if extra:
            entry["extra"] = extra

        line = json.dumps(entry, ensure_ascii=False)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line)


# Utility functions


def sha256_hex_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def compute_config_hash(config: Dict[str, Any]) -> str:
    # Exclude work_dir if present
    cfg = {k: v for k, v in config.items() if k != "work_dir"}
    s = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_consolidated_hash_from_artifacts(artifacts: List[Tuple[str, bytes]]) -> str:
    # artifacts: list of (name, bytes). Determine deterministic ordering by name resolved lower-case
    if not artifacts:
        return hashlib.sha256(b"").hexdigest()

    items = sorted(artifacts, key=lambda it: str(it[0]).lower())
    h = hashlib.sha256()
    for name, content in items:
        # Remove timestamps from content if any (best-effort) by not relying on them
        h.update(hashlib.sha256(content).digest())
    return h.hexdigest()


def atomic_write_json(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ckpt", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def full_jitter_retry(
    func: Callable,
    initial_delay: float = 1.0,
    max_delay: float = 120.0,
    max_attempts: int = 10,
):
    """Executes func() with full jitter retry. func should raise on failure.
    Returns func result or raises last exception.
    """
    attempt = 0
    while True:
        try:
            return func()
        except Exception:
            attempt += 1
            if attempt >= max_attempts:
                raise
            # delay = random.uniform(0, min(max_delay, initial_delay * 2**attempt))
            cap = min(max_delay, initial_delay * (2**attempt))
            delay = random.uniform(0, cap)
            time.sleep(delay)


# STEP_ARTIFACTS declarative structure


def _make_step_callback(i: int) -> Callable[[Path], List[Path]]:
    def cb(work_dir: Path) -> List[Path]:
        # dynamic file names, deterministic per step
        name = f"artifact_step_{i:03d}.bin"
        return [work_dir / name]

    return cb


STEP_ARTIFACTS: Dict[str, Callable[[Path], List[Path]]] = {}
for i in range(1, 53):
    STEP_ARTIFACTS[f"step_{i:03d}"] = _make_step_callback(i)


# SovereignRPAWorker


class SovereignRPAWorker:
    def __init__(
        self,
        session_id: str,
        work_dir: Path,
        config: Dict[str, Any],
        adapter: Optional[MockAutomationAdapter] = None,
        audit_logger: Optional[AuditLogger] = None,
        dry_run: bool = False,
        max_lock_age: int = 3600,
    ):
        self.session_id = session_id
        self.work_dir = Path(work_dir)
        self.config = dict(config)
        self.adapter = adapter or MockAutomationAdapter()
        self.audit = audit_logger or AuditLogger()
        self.dry_run = bool(dry_run)
        self.max_lock_age = int(max_lock_age)

        self.lock_dir = self.work_dir / f".lock_{self.session_id}"
        self.checkpoint_path = self.work_dir / "checkpoint.json"
        self._checkpoint: Dict[str, Any] = {}
        self._memory_artifacts: Dict[str, List[Tuple[str, bytes]]] = {}

        # Ensure work_dir exists (needed for lock dir even in dry-run)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def executar(self, tarefa: str, dados: Dict[str, Any]) -> Dict[str, Any]:
        tarefa_normalizada = str(tarefa or "").strip().lower()
        if tarefa_normalizada == "extrato_fgts":
            return self._executar_extrato_fgts(dados or {})
        return {
            "status": "error",
            "reason": f"tarefa_nao_suportada:{tarefa_normalizada or 'vazia'}",
        }

    def _resolve_fgts_runtime(self) -> Dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[2]
        profile_root = Path.home() / ".sovereign_rpa_caixa"
        profile_directory = str(self.config.get("profile_directory") or "Default")
        user_data_dir = self.config.get("user_data_dir") or str(
            profile_root / profile_directory
        )

        buster_candidates = [
            self.config.get("buster_extension_dir"),
            os.getenv("FGTS_BUSTER_EXTENSION_DIR"),
            os.getenv("SOVEREIGN_BUSTER_EXTENSION_DIR"),
            repo_root / "extensions" / "buster",
            repo_root / "extensions" / "buster.crx",
        ]
        buster_extension_dir = None
        for candidate in buster_candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate).expanduser()
            if candidate_path.exists():
                buster_extension_dir = str(candidate_path)
                break

        return {
            "fgts_url": self.config.get("fgts_url")
            or os.getenv("FGTS_CAIXA_URL")
            or "https://www.caixa.gov.br",
            "user_data_dir": str(Path(user_data_dir).expanduser()),
            "profile_directory": profile_directory,
            "buster_extension_dir": buster_extension_dir,
            "downloads_dir": str(
                Path(self.config.get("download_dir") or self.work_dir / "downloads")
            ),
        }

    def _executar_extrato_fgts(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import asyncio

            return asyncio.run(self._executar_extrato_fgts_async(dados))
        except RuntimeError as exc:
            return {"status": "error", "reason": f"event_loop:{exc}"}

    async def _executar_extrato_fgts_async(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {"status": "error", "reason": f"playwright_indisponivel:{exc}"}

        cpf = re.sub(r"\D", "", str(dados.get("cpf", "")))
        if not cpf:
            return {"status": "error", "reason": "cpf_ausente"}

        runtime = self._resolve_fgts_runtime()
        fgts_url = runtime["fgts_url"]
        user_data_dir = runtime["user_data_dir"]
        profile_directory = runtime["profile_directory"]
        extension_dir = runtime["buster_extension_dir"]
        downloads_dir = Path(runtime["downloads_dir"])
        downloads_dir.mkdir(parents=True, exist_ok=True)

        browser_args = ["--disable-blink-features=AutomationControlled"]
        if extension_dir and Path(extension_dir).exists():
            browser_args.extend(
                [
                    f"--disable-extensions-except={extension_dir}",
                    f"--load-extension={extension_dir}",
                ]
            )

        async def _captcha_visivel(page) -> bool:
            selectors = [
                "iframe[src*='hcaptcha']",
                "iframe[src*='recaptcha']",
                "iframe[src*='turnstile']",
                "#hcaptcha",
                "[data-sitekey]",
            ]
            for selector in selectors:
                try:
                    locator = page.locator(selector)
                    if await locator.count() > 0:
                        return True
                except Exception:
                    continue
            return False

        async def _esperar_captcha(page, timeout_seconds: int = 180) -> None:
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                if not await _captcha_visivel(page):
                    return
                await page.wait_for_timeout(2000)
            raise SovereignError("captcha_nao_resolvido")

        async def _tentar_download(page) -> Optional[Path]:
            botoes = [
                "button:has-text('Gerar PDF')",
                "button:has-text('Baixar PDF')",
                "button:has-text('Extrato')",
                "button:has-text('Consultar')",
                "button:has-text('Buscar')",
                "button[type='submit']",
                "input[type='submit']",
            ]
            links = [
                "a[href$='.pdf']",
                "a:has-text('PDF')",
                "a:has-text('Extrato')",
            ]

            for selector in botoes:
                try:
                    locator = page.locator(selector)
                    if await locator.count() == 0:
                        continue
                    async with page.expect_download(timeout=20000) as download_info:
                        await locator.first.click(force=True)
                    download = await download_info.value
                    suggested = download.suggested_filename or f"extrato_fgts_{cpf}.pdf"
                    final_path = downloads_dir / suggested
                    await download.save_as(str(final_path))
                    return final_path
                except Exception:
                    continue

            for selector in links:
                try:
                    locator = page.locator(selector)
                    if await locator.count() == 0:
                        continue
                    async with page.expect_download(timeout=20000) as download_info:
                        await locator.first.click(force=True)
                    download = await download_info.value
                    suggested = download.suggested_filename or f"extrato_fgts_{cpf}.pdf"
                    final_path = downloads_dir / suggested
                    await download.save_as(str(final_path))
                    return final_path
                except Exception:
                    continue

            return None

        context = None
        playwright = None
        try:
            playwright = await async_playwright().__aenter__()
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                accept_downloads=True,
                downloads_path=str(downloads_dir),
                args=browser_args,
                viewport={"width": 1366, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(fgts_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            try:
                await _esperar_captcha(page)
            except Exception:
                pass

            cpf_selectors = [
                "input[name='cpf']",
                "#cpf",
                "input[id*='cpf']",
                "input[placeholder*='CPF']",
                "input[aria-label*='CPF']",
            ]
            cpf_filled = False
            for selector in cpf_selectors:
                try:
                    locator = page.locator(selector)
                    if await locator.count() == 0:
                        continue
                    campo = locator.first
                    await campo.scroll_into_view_if_needed()
                    await campo.fill(cpf)
                    cpf_filled = True
                    break
                except Exception:
                    continue

            if not cpf_filled:
                return {
                    "status": "error",
                    "reason": "campo_cpf_nao_encontrado",
                    "source_url": fgts_url,
                }

            await page.wait_for_timeout(1000)

            download_path = await _tentar_download(page)
            if not download_path:
                return {
                    "status": "error",
                    "reason": "download_nao_localizado",
                    "source_url": fgts_url,
                }

            sha256 = None
            try:
                with open(download_path, "rb") as fh:
                    sha256 = hashlib.sha256(fh.read()).hexdigest()
            except Exception:
                sha256 = None

            pdf_name = None
            pdf_url = None
            try:
                from contabil_agente.services import pdf_store

                pdf_name = pdf_store.register_pdf(str(download_path), session_id=self.session_id)
                pdf_url = pdf_store.get_download_url(pdf_name)
            except Exception:
                try:
                    from contabil_agente.services import pdf_store

                    fallback_path = pdf_store.STATIC_DOWNLOADS / download_path.name
                    fallback_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(download_path, fallback_path)
                    pdf_name = fallback_path.name
                    pdf_url = f"/static/downloads/{fallback_path.name}"
                except Exception:
                    pdf_name = download_path.name
                    pdf_url = str(download_path)

            return {
                "status": "success",
                "tarefa": "extrato_fgts",
                "cpf": cpf,
                "path": str(download_path),
                "pdf_name": pdf_name,
                "pdf_url": pdf_url,
                "sha256": sha256,
                "source_url": fgts_url,
            }
        finally:
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if playwright:
                    await playwright.__aexit__(None, None, None)
            except Exception:
                pass

    def __enter__(self) -> "SovereignRPAWorker":
        self.acquire_lock()
        self.load_or_init_checkpoint()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc:
                # log exception
                self.audit.log("error", "__exit__", 0, "", exception=exc)
        finally:
            self.release_lock()

    def acquire_lock(self):
        try:
            self.lock_dir.mkdir(exist_ok=False)
        except FileExistsError:
            # check stale
            try:
                st = self.lock_dir.stat()
                age = time.time() - st.st_mtime
                if age > self.max_lock_age:
                    # remove stale lock
                    try:
                        shutil.rmtree(self.lock_dir)
                    except Exception:
                        pass
                    # try again
                    try:
                        self.lock_dir.mkdir(exist_ok=False)
                    except Exception as e:
                        raise SovereignError("Sessão ativa") from e
                else:
                    raise SovereignError("Sessão ativa")
            except FileNotFoundError:
                # race, try again
                try:
                    self.lock_dir.mkdir(exist_ok=False)
                except Exception as e:
                    raise SovereignError("Sessão ativa") from e

    def release_lock(self):
        try:
            if self.lock_dir.exists():
                try:
                    shutil.rmtree(self.lock_dir)
                except Exception:
                    try:
                        self.lock_dir.rmdir()
                    except Exception:
                        pass
        except Exception:
            pass

    def load_or_init_checkpoint(self):
        cfg_hash = compute_config_hash(self.config)
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # validate config
                if data.get("config_hash") != cfg_hash:
                    raise SovereignIntegrityError("Config hash diverge do checkpoint")
                self._checkpoint = data
            except SovereignIntegrityError:
                raise
            except Exception:
                # If corrupted, start fresh but keep copy
                bak = self.checkpoint_path.with_suffix(".corrupt")
                try:
                    shutil.copy2(self.checkpoint_path, bak)
                except Exception:
                    pass
                self._checkpoint = {
                    "session_id": self.session_id,
                    "config_hash": cfg_hash,
                    "steps": {},
                }
        else:
            self._checkpoint = {
                "session_id": self.session_id,
                "config_hash": cfg_hash,
                "steps": {},
            }

    def save_checkpoint(self):
        if self.dry_run:
            return
        cp = dict(self._checkpoint)
        # compute checkpoint hash
        cp_no_hash = dict(cp)
        cp_no_hash.pop("checkpoint_hash", None)
        s = json.dumps(cp_no_hash, sort_keys=True, default=str)
        cp_no_hash["checkpoint_hash"] = hashlib.sha256(s.encode("utf-8")).hexdigest()
        atomic_write_json(self.checkpoint_path, cp_no_hash)
        self._checkpoint = cp_no_hash

    def _ensure_step_artifacts(self, step_id: str) -> List[Path]:
        cb = STEP_ARTIFACTS.get(step_id)
        if cb is None:
            raise SovereignError(f"Step desconhecido: {step_id}")
        return cb(self.work_dir)

    def _delete_artifacts(self, artifacts: List[Path]):
        for p in artifacts:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    def _write_artifacts_to_disk(self, artifacts: List[Tuple[str, bytes]]):
        for name, content in artifacts:
            p = self.work_dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "wb") as f:
                f.write(content)

    def _compute_artifact_hashes(self, artifacts: List[Tuple[str, bytes]]) -> List[str]:
        # compute sha256_hex(conteúdo) for each artifact
        hs = [sha256_hex_bytes(content) for _, content in artifacts]
        # order deterministically by artifact name (case-insensitive lower)
        return [h for _, h in sorted(zip([n.lower() for n, _ in artifacts], hs))]

    def _compute_consolidated_hash(self, artifacts: List[Tuple[str, bytes]]) -> str:
        return compute_consolidated_hash_from_artifacts(artifacts)

    def run_step(self, step_id: str, retry_opts: Optional[Dict[str, Any]] = None):
        retry_opts = retry_opts or {}
        expected = self._ensure_step_artifacts(step_id)

        def _do():
            start = time.time()
            artifacts = self.adapter.perform_step(step_id, expected)
            duration_ms = (time.time() - start) * 1000.0

            # compute hashes
            consolidated = self._compute_consolidated_hash(artifacts)
            artifact_hashes = self._compute_artifact_hashes(artifacts)

            # handle dry-run: keep in-memory store
            if self.dry_run:
                self._memory_artifacts[step_id] = artifacts
            else:
                # write artifacts to disk atomically (write files)
                self._write_artifacts_to_disk(artifacts)

            # update checkpoint
            self._checkpoint.setdefault("steps", {})[step_id] = {
                "status": "completed",
                "artifact_hashes": artifact_hashes,
                "consolidated_hash": consolidated,
                "completed_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
            self.save_checkpoint()

            self.audit.log("info", step_id, duration_ms, consolidated)
            return True

        # If checkpoint indicates completed, verify artifacts
        steps = self._checkpoint.setdefault("steps", {})
        if step_id in steps and steps[step_id].get("status") == "completed":
            # verify existence and hash
            try:
                prev_hash = steps[step_id].get("consolidated_hash", "")
                # reconstruct artifacts from disk or memory
                artifacts: List[Tuple[str, bytes]] = []
                if self.dry_run:
                    artifacts = self._memory_artifacts.get(step_id, [])
                else:
                    expected_paths = self._ensure_step_artifacts(step_id)
                    for p in expected_paths:
                        if not p.exists():
                            raise FileNotFoundError(p)
                        with open(p, "rb") as f:
                            artifacts.append((p.name, f.read()))

                consolidated = self._compute_consolidated_hash(artifacts)
                if consolidated == prev_hash:
                    # already done
                    return True
                else:
                    # mismatch -> delete and reprocess
                    if not self.dry_run:
                        self._delete_artifacts(expected)
                    # mark as pending
                    steps.pop(step_id, None)
                    self.save_checkpoint()
            except Exception:
                # missing artifacts -> reprocess
                steps.pop(step_id, None)
                try:
                    self.save_checkpoint()
                except Exception:
                    pass

        # run with retry
        initial_delay = float(retry_opts.get("initial_delay", 1.0))
        max_delay = float(retry_opts.get("max_delay", 120.0))
        max_attempts = int(retry_opts.get("max_attempts", 10))

        def _call():
            return _do()

        try:
            full_jitter_retry(
                _call,
                initial_delay=initial_delay,
                max_delay=max_delay,
                max_attempts=max_attempts,
            )
        except Exception as e:
            # audit and rethrow
            self.audit.log("error", step_id, 0, "", exception=e)
            raise

        return True

    def run_workflow(
        self, start: int = 1, end: int = 52, retry_opts: Optional[Dict[str, Any]] = None
    ):
        retry_opts = retry_opts or {}
        for i in range(start, end + 1):
            step_id = f"step_{i:03d}"
            # Logical retry loop: attempt up to 3 times for intermittent RuntimeError
            attempts = 0
            while True:
                try:
                    self.run_step(step_id, retry_opts=retry_opts)
                    # success -> proceed to next step
                    break
                except SovereignComplianceError:
                    raise
                except RuntimeError as e:
                    # Capture memory snapshot if possible
                    attempts += 1
                    mem_mb = 0.0
                    try:
                        import psutil

                        proc = psutil.Process(os.getpid())
                        mem_mb = proc.memory_info().rss / (1024 * 1024)
                    except Exception:
                        mem_mb = 0.0

                    # Audit the interruption with step and memory
                    try:
                        self.audit.log(
                            "error",
                            step_id,
                            0,
                            "",
                            exception=e,
                            extra={"attempt": attempts, "mem_mb": mem_mb},
                        )
                    except Exception:
                        pass

                    # If max attempts reached, raise a descriptive RuntimeError
                    if attempts >= 3:
                        raise RuntimeError(
                            f"Simulated intermittent critical interruption at {step_id}; attempts={attempts}; mem_mb={mem_mb}"
                        ) from e

                    # Backoff before retrying (small, deterministic)
                    try:
                        time.sleep(1 * attempts)
                    except Exception:
                        pass
                    # retry loop continues
                    continue
                except Exception as e:
                    # Non-retriable exception: log and raise with step context
                    try:
                        mem_mb = 0.0
                        import psutil

                        proc = psutil.Process(os.getpid())
                        mem_mb = proc.memory_info().rss / (1024 * 1024)
                    except Exception:
                        mem_mb = 0.0
                    self.audit.log(
                        "error", step_id, 0, "", exception=e, extra={"mem_mb": mem_mb}
                    )
                    raise


if __name__ == "__main__":
    # Quick smoke demo
    wk = Path(tempfile.gettempdir()) / "sovereign_demo"
    cfg = {"env": "demo"}
    alog = AuditLogger()
    inj = FaultInjector()
    adapter = MockAutomationAdapter(injector=inj)

    with SovereignRPAWorker(
        "demo", wk, cfg, adapter=adapter, audit_logger=alog, dry_run=True
    ) as w:
        w.run_workflow(1, 3)
