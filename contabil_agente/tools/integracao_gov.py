import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from playwright.async_api import async_playwright

# Try to import AccountingBot from executor_motor
import importlib.util

try:
    from executor_motor import AccountingBot
except Exception:
    try:
        executor_motor_path = os.path.join(
            os.path.dirname(__file__), "executor_motor.py"
        )
        spec = importlib.util.spec_from_file_location(
            "executor_motor", executor_motor_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        AccountingBot = module.AccountingBot
    except Exception:
        AccountingBot = None

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)
logger = logging.getLogger("integracao_gov")

_BASE_DIR = Path(__file__).resolve().parent.parent
DIRECT_PGMEI_URL = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"


async def detect_hcaptcha(page) -> bool:
    try:
        el = await page.query_selector("#hcaptcha")
        if el:
            return True
    except Exception:
        pass
    try:
        for f in page.frames:
            try:
                if f.url and "hcaptcha" in f.url:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def wait_for_manual_solve(page, timeout_seconds: Optional[int] = None) -> bool:
    """Aguarda intervenção manual. Se `timeout_seconds` for None, aguarda indefinidamente
    até que o iframe do hCaptcha desapareça ou o operador pressione Enter.
    """
    start = time.time()
    logger.warning(
        "hCaptcha detectado — aguardar resolução manual%s",
        f" (timeout {timeout_seconds}s)" if timeout_seconds else "",
    )
    while True:
        try:
            el = await page.query_selector("#hcaptcha")
            if not el:
                logger.info("hCaptcha aparentemente resolvido")
                return True
        except Exception:
            pass

        # allow operator to press Enter in console to continue
        try:
            if sys.stdin and sys.stdin in (sys.__stdin__,):
                import select

                if select.select([sys.stdin], [], [], 0)[0]:
                    _ = sys.stdin.readline()
                    logger.info("Sinal do operador recebido — prosseguindo")
                    return True
        except Exception:
            pass

        if timeout_seconds is not None and (time.time() - start) > timeout_seconds:
            logger.error("Timeout aguardando resolução do hCaptcha")
            return False

        await asyncio.sleep(2)


async def _attempt_download(page, downloads_dir: Path) -> Optional[Path]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    # try anchors with .pdf
    try:
        anchors = await page.query_selector_all("a")
        for a in anchors:
            try:
                href = await a.get_attribute("hre")
                if href and href.lower().endswith(".pd"):
                    try:
                        async with page.expect_download(timeout=10000) as dd:
                            await a.click()
                        dl = await dd.value
                        out = downloads_dir / (
                            dl.suggested_filename
                            or f"mei_{int(datetime.now().timestamp())}.pd"
                        )
                        await dl.save_as(str(out))
                        logger.info("Download salvo via anchor: %s", out)
                        return out
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    # try elements with download attribute
    selectors = ["a[download]", "a[href$='.pdf']"]
    for sel in selectors:
        try:
            elems = await page.query_selector_all(sel)
            for e in elems:
                try:
                    async with page.expect_download(timeout=10000) as dd:
                        await e.click()
                    dl = await dd.value
                    out = downloads_dir / (
                        dl.suggested_filename
                        or f"mei_{int(datetime.now().timestamp())}.pdf"
                    )
                    await dl.save_as(str(out))
                    logger.info("Download salvo via selector %s: %s", sel, out)
                    return out
                except Exception:
                    continue
        except Exception:
            continue

    logger.warning("Não foi possível localizar download automático de PDF")
    return None


# Guarded imports for infra services used by the robot
try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None

try:
    from contabil_agente.services.evidence_service import EvidenceService
except Exception:
    EvidenceService = None

try:
    from contabil_agente.services import get_document_service_class
except Exception:
    get_document_service_class = None

# Guarded imports for Parser and Delivery
try:
    from contabil_agente.services.parser_service import ParserService
except Exception:
    ParserService = None

try:
    from contabil_agente.services.delivery_service import DeliveryService
except Exception:
    DeliveryService = None

try:
    from contabil_agente.services.secret_manager import SecretManager
except Exception:
    SecretManager = None


class RobotExecutor:
    """O motor de execução resiliente (OOP).

    Encapsula health-check, máquina de estados e integrações com
    audit/evidence/document services. Projetado para não depender do Chat.
    """

    def __init__(self, page, cnpj: str, downloads_dir: Path, max_transitions: int = 12):
        self.page = page
        self.cnpj = cnpj
        self.downloads_dir = downloads_dir
        self.max_transitions = max_transitions
        self.timeouts = {"normal": 30, "slow": 60, "critical": 120}
        self.last_nav_time = None
        self.metrics = {"login": 0.0, "navigation": 0.0, "download": 0.0}

    def verificar_disponibilidade_robo(self) -> Dict[str, bool]:
        """Verifica disponibilidade de infra local (audit/document/evidence)."""
        out = {"audit": False, "document": False, "evidence": False}
        try:
            if AuditService:
                try:
                    _ = AuditService.get_instance()
                    out["audit"] = True
                except Exception:
                    out["audit"] = True
        except Exception:
            out["audit"] = False

        try:
            if get_document_service_class:
                DocCls = get_document_service_class()
                if DocCls:
                    out["document"] = True
        except Exception:
            out["document"] = False

        try:
            if EvidenceService:
                out["evidence"] = True
        except Exception:
            out["evidence"] = False

        return out

    def _current_timeout(self) -> int:
        if self.last_nav_time is None:
            return self.timeouts["normal"]
        if self.last_nav_time > self.timeouts["normal"]:
            return self.timeouts["slow"]
        return self.timeouts["normal"]

    async def _take_evidence(self, name: str) -> Optional[str]:
        try:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            fn = self.downloads_dir / f"{self.cnpj}_{name}_{int(time.time())}.png"
            await self.page.screenshot(path=str(fn), full_page=True)
            if EvidenceService:
                try:
                    ev = EvidenceService(base_dir=str(self.downloads_dir))
                    ev.register(str(fn), metadata={"cnpj": self.cnpj, "state": name})
                except Exception:
                    logger.debug("evidence_service failed to register %s", fn)
            return str(fn)
        except Exception:
            logger.debug("failed to take evidence %s", name)
            return None

    def _audit(self, msg: str, level: str = "info") -> None:
        try:
            if AuditService:
                try:
                    a = AuditService.get_instance()
                    a.log_operation(msg)
                    return
                except Exception:
                    logger.debug("audit service call failed")
        except Exception:
            pass
        getattr(logger, level)("AUDIT: %s", msg)

    async def _click_resilient(self, *selectors: str) -> bool:
        """Tenta múltiplos seletores usando get_by_role/get_by_text, com fallback."""
        for sel in selectors:
            try:
                if sel.startswith("role:"):
                    parts = sel.split("|", 1)
                    role = parts[0].split(":", 1)[1]
                    name = parts[1] if len(parts) > 1 else None
                    loc = (
                        self.page.get_by_role(role, name=name)
                        if name
                        else self.page.get_by_role(role)
                    )
                    if await loc.count() > 0:
                        await loc.first.click()
                        return True
                elif sel.startswith("text:"):
                    text = sel.split(":", 1)[1]
                    loc = self.page.get_by_text(text)
                    if await loc.count() > 0:
                        await loc.first.click()
                        return True
                else:
                    el = await self.page.query_selector(sel)
                    if el:
                        await el.click()
                        return True
            except Exception:
                continue
        return False

    async def run(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "failed",
            "cnpj": self.cnpj,
            "metrics": self.metrics,
        }
        health = self.verificar_disponibilidade_robo()
        self._audit(f"ROBO_HEALTH {json.dumps(health)}")

        transitions = 0
        state = "validacao"

        try:
            while transitions < self.max_transitions:
                transitions += 1
                try:
                    body = (await self.page.content()).lower()
                except Exception:
                    body = ""

                # maintenance
                if any(k in body for k in ("manuten", "indisponiv", "em manutenção")):
                    await self._take_evidence("maintenance")
                    self._audit(
                        f"SISTEMA_MAINTENANCE detected for {self.cnpj}", level="error"
                    )
                    try:
                        await self.page.close()
                    except Exception:
                        pass
                    result.update({"status": "maintenance"})
                    return result

                # pendencias
                if any(
                    k in body for k in ("pendência", "pendencia", "dívida", "divida")
                ):
                    await self._take_evidence("pendencia_detectada")
                    debt_text = ""
                    try:
                        debt_text = await self.page.get_by_text(
                            "Pendência"
                        ).text_content()
                    except Exception:
                        try:
                            debt_text = await self.page.evaluate(
                                "() => document.body.innerText"
                            )
                        except Exception:
                            debt_text = ""
                    self._audit(f"PENDENCIA_DETECTADA for {self.cnpj}: {debt_text}")

                # already emitted
                if any(
                    k in body for k in ("já emitida", "ja emitida", "já foi emitida")
                ):
                    await self._take_evidence("already_emitted")
                    self._audit(f"SUCESSO_EXISTENTE for {self.cnpj}")
                    dl = await _attempt_download(self.page, self.downloads_dir)
                    if dl:
                        result.update({"status": "success_existing", "path": str(dl)})
                        return result

                # VALIDACAO: login
                if state == "validacao":
                    t0 = time.time()
                    clicked = await self._click_resilient(
                        "role:button|Acessar",
                        "text:Acessar",
                        "button:has-text('Acessar')",
                    )
                    self.metrics["login"] = time.time() - t0
                    if clicked:
                        await self._take_evidence("after_login_click")
                        self._audit(f"LOGIN_CLICKED for {self.cnpj}")
                        state = "navegacao"
                        continue

                # captcha handling (manual solved assumed before run)
                try:
                    if await detect_hcaptcha(self.page):
                        solved = await wait_for_manual_solve(
                            self.page, timeout_seconds=self._current_timeout()
                        )
                        if not solved:
                            self._audit(
                                f"HCAPTCHA_TIMEOUT for {self.cnpj}", level="error"
                            )
                            result.update(
                                {"status": "needs_manual", "reason": "hcaptcha"}
                            )
                            return result
                        self._audit(f"HCAPTCHA_SOLVED for {self.cnpj}")
                except Exception:
                    logger.debug("hcaptcha detection error")

                # NAVEGACAO
                if state == "navegacao":
                    t0 = time.time()
                    clicked = await self._click_resilient(
                        "text:Pagamentos", "text:Extratos", "role:link|Pagamentos"
                    )
                    self.metrics["navigation"] = time.time() - t0
                    if clicked:
                        await self._take_evidence("pagamentos_opened")
                        self._audit(f"NAV_PAGAMENTOS for {self.cnpj}")
                        state = "emissao"
                        continue

                # EMISSAO / DOWNLOAD
                if state == "emissao":
                    t0 = time.time()
                    try:
                        sel = self.page.get_by_role("combobox")
                        if await sel.count() > 0:
                            try:
                                await sel.first.select_option(value="2026")
                            except Exception:
                                pass
                        else:
                            await self._click_resilient("text:2026", "role:link|2026")
                    except Exception:
                        pass

                    try:
                        btn_clicked = await self._click_resilient(
                            "role:button|Gerar PDF", "text:Gerar PDF", "text:Download"
                        )
                        if btn_clicked:
                            try:
                                async with self.page.expect_download(
                                    timeout=self._current_timeout() * 1000
                                ) as dd:
                                    await asyncio.sleep(0.5)
                                dl = await dd.value
                                out = self.downloads_dir / (
                                    dl.suggested_filename or f"extrato_{self.cnpj}.pdf"
                                )
                                await dl.save_as(str(out))
                                self.metrics["download"] = time.time() - t0
                                new_name = (
                                    self.downloads_dir
                                    / f"extrato_2026_{self.cnpj.replace('/', '_').replace('.', '_')}.pdf"
                                )
                                try:
                                    out.rename(new_name)
                                except Exception:
                                    new_name = out
                                self._audit(
                                    f"DOWNLOAD_OK for {self.cnpj} -> {new_name}"
                                )
                                await self._take_evidence("download_ok")
                                try:
                                    if get_document_service_class:
                                        DocCls = get_document_service_class()
                                        if DocCls:
                                            doc = DocCls()
                                            if hasattr(doc, "ingest_document"):
                                                doc.ingest_document(str(new_name))
                                except Exception:
                                    logger.debug("document service ingest failed")
                                result.update(
                                    {
                                        "status": "success",
                                        "path": str(new_name),
                                        "metrics": self.metrics,
                                    }
                                )
                                return result
                            except Exception:
                                dl2 = await _attempt_download(
                                    self.page, self.downloads_dir
                                )
                                if dl2:
                                    self.metrics["download"] = time.time() - t0
                                    result.update(
                                        {
                                            "status": "success",
                                            "path": str(dl2),
                                            "metrics": self.metrics,
                                        }
                                    )
                                    return result
                    except Exception:
                        logger.debug("download attempt failed")

                # session expired detection
                if any(
                    k in body
                    for k in (
                        "sessão expirada",
                        "sessao expirada",
                        "login novamente",
                        "faça login",
                    )
                ):
                    await self._take_evidence("session_expired")
                    self._audit(f"SESSION_EXPIRED for {self.cnpj}", level="error")
                    try:
                        print("\a")
                    except Exception:
                        pass
                    result.update({"status": "session_expired"})
                    try:
                        await self.page.close()
                    except Exception:
                        pass
                    return result

                await asyncio.sleep(1)

            dl = await _attempt_download(self.page, self.downloads_dir)
            if dl:
                result.update(
                    {"status": "success", "path": str(dl), "metrics": self.metrics}
                )
                return result

            result.update({"status": "no_result", "metrics": self.metrics})
            return result

        except Exception as e:
            logger.exception("Erro em RobotExecutor.run: %s", e)
            await self._take_evidence("exception")
            self._audit(f"ERROR_EXECUTION for {self.cnpj}: {e}", level="error")
            result.update({"status": "failed", "reason": str(e)})
            return result


async def executar_fluxo_extracao(
    page, cnpj: str, downloads_dir: Path, max_transitions: int = 12
) -> Dict[str, Any]:
    """Backward-compatible wrapper that uses RobotExecutor."""
    execr = RobotExecutor(
        page=page,
        cnpj=cnpj,
        downloads_dir=downloads_dir,
        max_transitions=max_transitions,
    )
    return await execr.run()


async def process_single_client(
    page, cnpj: str, downloads_dir: Optional[Path] = None
) -> Dict[str, Any]:
    downloads_dir = downloads_dir or (_BASE_DIR / "downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    result = {"status": "failed", "cnpj": cnpj}

    try:
        if getattr(page, "is_closed", lambda: False)():
            result["reason"] = "page_closed"
            return result

        # Navigate with polite waits and fallbacks
        try:
            await page.goto(
                DIRECT_PGMEI_URL, timeout=60000, wait_until="domcontentloaded"
            )
        except Exception:
            try:
                await page.goto(
                    DIRECT_PGMEI_URL, timeout=120000, wait_until="domcontentloaded"
                )
            except Exception as e:
                result["reason"] = f"goto_failed: {e}"
                return result

        # try to fill CNPJ
        candidates = [
            "#cnpj",
            "input[id*=cnpj]",
            "input[name*=cnpj]",
            "input[placeholder*=CNPJ]",
            "input[aria-label*=CNPJ]",
            "input[type='tel']",
            "input[type='text']",
        ]
        for sel in candidates:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                try:
                    await el.click()
                except Exception:
                    try:
                        box = await el.bounding_box()
                        if box:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                    except Exception:
                        pass
                try:
                    await page.keyboard.down("Control")
                    await page.keyboard.press("a")
                    await page.keyboard.up("Control")
                except Exception:
                    try:
                        await page.keyboard.press("Control+a")
                    except Exception:
                        pass
                await page.keyboard.press("Delete")
                await page.keyboard.type(cnpj, delay=80)
                try:
                    await page.evaluate(
                        "(sel)=>{\n"
                        "  const e=document.querySelector(sel);\n"
                        "  if(e){\n"
                        "    e.dispatchEvent(new Event('input',{bubbles:true}));\n"
                        "    e.dispatchEvent(new Event('change',{bubbles:true}));\n"
                        "    e.blur();\n"
                        "  }\n"
                        "}",
                        sel,
                    )
                except Exception:
                    pass
                logger.info("CNPJ preenchido usando %s", sel)
                break
            except Exception:
                continue

        # detect hcaptcha now (after fill) and wait briefly if present
        try:
            if await detect_hcaptcha(page):
                solved = await wait_for_manual_solve(page)
                if not solved:
                    return {"status": "needs_manual", "reason": "hcaptcha_detected"}
        except Exception:
            logger.debug("Erro detectando hCaptcha; prosseguindo")

        # try submit buttons
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Consultar')",
            "button:has-text('Buscar')",
        ]
        download_path = None
        for s in submit_selectors:
            try:
                btn = await page.query_selector(s)
                if not btn:
                    continue
                try:
                    async with page.expect_download(timeout=15000) as dd:
                        await btn.click()
                    dl = await dd.value
                    out = downloads_dir / (
                        dl.suggested_filename
                        or f"mei_{int(datetime.now().timestamp())}.pdf"
                    )
                    await dl.save_as(str(out))
                    download_path = out
                    break
                except Exception:
                    try:
                        await btn.click()
                        await asyncio.sleep(2)
                    except Exception:
                        continue
            except Exception:
                continue

        if not download_path:
            out = await _attempt_download(page, downloads_dir)
            if out:
                download_path = out

        if not download_path:
            result["status"] = "failed"
            result["reason"] = "no_download"
            return result

        # compute sha256
        try:
            with open(download_path, "rb") as fh:
                data = fh.read()
            sha = hashlib.sha256(data).hexdigest()
        except Exception:
            sha = None

        meta = {
            "cnpj": cnpj,
            "path": str(download_path),
            "timestamp": int(datetime.now().timestamp()),
            "sha256": sha,
        }
        try:
            meta_path = downloads_dir / (download_path.stem + ".json")
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.debug("Falha ao salvar metadados", exc_info=True)

        result.update({"status": "success", "path": str(download_path), "sha256": sha})
        return result

    except Exception as e:
        logger.exception("Erro em process_single_client: %s", e)
        result.update({"status": "failed", "reason": str(e)})
        return result


async def processar_empresa_unica(
    page, cnpj: str, modo: str = "strict", downloads_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """Orquestração ponta-a-ponta para um único CNPJ.

    modos: 'strict', 'best_effort', 'dry_run'
    Implementa retries, circuit-breaker on low confidence, integrity checks,
    rollback and audit/evidence integration.
    """
    downloads_dir = (
        Path(downloads_dir) if downloads_dir else (Path(_BASE_DIR) / "downloads")
    )
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # configuration
    MAX_ATTEMPTS = 3
    MAX_STEP_TIMEOUT = 300  # seconds per step (hard cap)

    metrics: Dict[str, float] = {"download_time": 0.0, "parse_time": 0.0, "total": 0.0}
    audit_prefix = f"PROCESS_SINGLE {cnpj}"

    def _audit(msg: str, level: str = "info"):
        try:
            if AuditService:
                a = AuditService.get_instance()
                a.log_operation(msg)
                return
        except Exception:
            pass
        getattr(logger, level)(msg)

    async def _retry_step(coro_func, name: str):
        attempt = 0
        last_exc = None
        while attempt < MAX_ATTEMPTS:
            attempt += 1
            start = time.time()
            try:
                res = await asyncio.wait_for(coro_func(), timeout=MAX_STEP_TIMEOUT)
                metrics[name + "Time"] = time.time() - start
                _audit(
                    f"{audit_prefix} STEP_OK {name} attempt={attempt} time={metrics[name + 'Time']}"
                )
                return res
            except asyncio.TimeoutError as te:
                last_exc = te
                _audit(
                    f"{audit_prefix} STEP_TIMEOUT {name} attempt={attempt}",
                    level="warning",
                )
            except Exception as e:
                last_exc = e
                _audit(
                    f"{audit_prefix} STEP_ERROR {name} attempt={attempt} error={e}",
                    level="warning",
                )
            await asyncio.sleep(2**attempt)
        raise last_exc

    start_total = time.time()

    # Pre-flight: health checks for delivery, document, evidence
    try:
        dm_health = {}
        if DeliveryService:
            try:
                ds = DeliveryService()
                dm_health = ds.health_check()
            except Exception:
                dm_health = {"smtp": False, "whatsapp": False}
        _audit(f"{audit_prefix} PREFLIGHT delivery_health={json.dumps(dm_health)}")
    except Exception:
        pass

    # Step 1: Download via executar_fluxo_extracao (retry)
    download_path: Optional[Path] = None

    async def _step_download():
        nonlocal download_path
        if modo == "dry_run":
            _audit(f"{audit_prefix} DRY_RUN skip download")
            return None
        res = await executar_fluxo_extracao(page, cnpj, downloads_dir)
        if res.get("status") not in ("success", "success_existing"):
            raise RuntimeError(f"download_failed: {res}")
        download_path = Path(res.get("path")) if res.get("path") else None
        return download_path

    try:
        await _retry_step(_step_download, "download")
    except Exception as e:
        _audit(f"{audit_prefix} DOWNLOAD_FAILED {e}", level="error")
        # rollback
        try:
            await RobotExecutor(page, cnpj, downloads_dir).page.close()
        except Exception:
            pass
        return {"status": "failed", "reason": "download_failed", "error": str(e)}

    # Step 2: integrity check (sha256 + optional signature)
    try:
        if download_path and download_path.exists():
            with open(download_path, "rb") as fh:
                data = fh.read()
            sha = hashlib.sha256(data).hexdigest()
            _audit(f"{audit_prefix} SHA256 {sha}")
            # placeholder signature validation
            sig_ok = False
            try:
                # hypothetical tool: validate_signature(path)
                from contabil_agente.tools import assinatura_tool  # type: ignore

                sig_ok = assinatura_tool.validate_signature(str(download_path))
            except Exception:
                sig_ok = False
            if not sig_ok:
                _audit(f"{audit_prefix} SIGNATURE_MISSING_OR_INVALID", level="warning")
        else:
            _audit(f"{audit_prefix} NO_DOWNLOAD_FILE", level="error")
            return {"status": "failed", "reason": "no_file"}
    except Exception as e:
        _audit(f"{audit_prefix} INTEGRITY_CHECK_ERROR {e}", level="error")

    # Step 3: parse PDF
    parsed = None
    try:

        async def _step_parse():
            nonlocal parsed
            if ParserService is None:
                raise RuntimeError("parser_service_unavailable")
            ps = ParserService()
            t0 = time.time()
            parsed = await asyncio.to_thread(ps.parse_pdf, str(download_path))
            metrics["parse_time"] = time.time() - t0
            return parsed

        await _retry_step(_step_parse, "parse")
    except Exception as e:
        _audit(f"{audit_prefix} PARSE_FAILED {e}", level="error")
        # rollback and evidence
        try:
            await RobotExecutor(page, cnpj, downloads_dir)._take_evidence(
                "parse_failed"
            )
        except Exception:
            pass
        return {"status": "failed", "reason": "parse_failed", "error": str(e)}

    # compute confidence heuristically
    confidence = 0.0
    try:
        issues = getattr(parsed, "anomalies", [])
        if not issues and parsed.value and parsed.due_date:
            confidence = 0.99
        elif parsed.value and parsed.due_date:
            confidence = 0.9
        else:
            confidence = 0.5
        _audit(f"{audit_prefix} PARSER_CONFIDENCE {confidence}")
    except Exception:
        confidence = 0.0

    if modo == "strict" and confidence < 0.95:
        _audit(
            f"{audit_prefix} CIRCUIT_BREAKER_OPEN confidence={confidence}",
            level="error",
        )
        # capture evidence and abort
        try:
            await RobotExecutor(page, cnpj, downloads_dir)._take_evidence(
                "circuit_breaker"
            )
        except Exception:
            pass
        return {
            "status": "aborted",
            "reason": "low_confidence",
            "confidence": confidence,
        }

    # Step 4: ingest document (optional in dry_run)
    if modo != "dry_run":
        try:
            if get_document_service_class:
                DocCls = get_document_service_class()
                if DocCls:
                    doc = DocCls()
                    try:
                        if hasattr(doc, "ingest_document"):
                            await asyncio.to_thread(
                                doc.ingest_document, str(download_path)
                            )
                            _audit(f"{audit_prefix} DOCUMENT_INGESTED {download_path}")
                    except Exception as e:
                        _audit(
                            f"{audit_prefix} DOCUMENT_INGEST_ERROR {e}", level="warning"
                        )
        except Exception:
            pass

    # Step 5: delivery (mock or real)
    delivery_res = None
    try:
        if modo == "dry_run":
            _audit(f"{audit_prefix} DRY_RUN skipping delivery")
        else:
            if DeliveryService:
                ds = DeliveryService()
                # priority escalate for anomalies
                prio = "normal"
                if getattr(parsed, "anomalies", []):
                    prio = "high"
                # For demonstration use a placeholder recipient
                delivery_res = ds.send_email(
                    to="contato@cliente.test",
                    subject=f"Extrato {cnpj}",
                    body="Segue extrato.",
                    attachments=[str(download_path)],
                    priority=prio,
                )
                _audit(f"{audit_prefix} DELIVERY_RESULT {delivery_res}")
    except Exception as e:
        _audit(f"{audit_prefix} DELIVERY_ERROR {e}", level="warning")

    metrics["total"] = time.time() - start_total
    _audit(f"{audit_prefix} COMPLETE metrics={json.dumps(metrics)}")
    return {
        "status": "ok",
        "path": str(download_path),
        "metrics": metrics,
        "confidence": confidence,
        "delivery": delivery_res,
    }


async def worker(queue: "asyncio.Queue[Optional[str]]", bot: Any) -> None:
    """Worker que processa CNPJs; usa `None` como sentinel para encerrar graciosamente.

    Cria um contexto limpo por tarefa quando o `AccountingBot` expõe `_browser`.
    """
    while True:
        cnpj = await queue.get()
        try:
            if cnpj is None:
                queue.task_done()
                break

            res = {"status": "failed", "reason": "unknown"}
            # start fresh Playwright/browser/context per task
            pw = await async_playwright().__aenter__()
            try:
                browser = await pw.chromium.launch(headless=False)
                contexto = await browser.new_context()
                page = await contexto.new_page()
                try:
                    try:
                        await page.goto(
                            DIRECT_PGMEI_URL,
                            timeout=60000,
                            wait_until="domcontentloaded",
                        )
                    except Exception:
                        try:
                            await page.goto(
                                DIRECT_PGMEI_URL,
                                timeout=120000,
                                wait_until="domcontentloaded",
                            )
                        except Exception as e:
                            logger.exception("Erro navegando para PGMEI: %s", e)

                    # hygiene + type
                    try:
                        locator = page.locator("#cnpj")
                        if await locator.count() > 0:
                            await locator.fill("")
                            await locator.type(cnpj, delay=150)
                            logger.info("CNPJ digitado (modo humano) em #cnpj")
                        else:
                            for sel in [
                                "input[id*=cnpj]",
                                "input[name*=cnpj]",
                                "input[placeholder*=CNPJ]",
                            ]:
                                try:
                                    loc = page.locator(sel)
                                    if await loc.count() > 0:
                                        await loc.fill("")
                                        await loc.type(cnpj, delay=150)
                                        logger.info(
                                            "CNPJ digitado (modo humano) em %s", sel
                                        )
                                        break
                                except Exception:
                                    continue
                    except Exception as e:
                        logger.debug("Erro tentando preencher CNPJ: %s", e)

                    # Execute resilient extraction motor (assumes manual captcha solved)
                    try:
                        downloads_dir = Path(_BASE_DIR) / "downloads"
                        res = await executar_fluxo_extracao(page, cnpj, downloads_dir)
                    except Exception as e:
                        logger.exception(
                            "Erro ao executar fluxo de extração para %s: %s", cnpj, e
                        )
                        res = {"status": "failed", "reason": str(e)}
                except Exception as e:
                    logger.exception("Erro durante task do navegador: %s", e)
                finally:
                    try:
                        if page and not getattr(page, "is_closed", lambda: False)():
                            await page.close()
                    except Exception:
                        pass
                    try:
                        if contexto:
                            await contexto.close()
                    except Exception:
                        pass
                    try:
                        if browser:
                            await browser.close()
                    except Exception:
                        pass
            finally:
                try:
                    await async_playwright().__aexit__(None, None, None)
                except Exception:
                    pass

            logger.info("Resultado para %s: %s", cnpj, res)
        except Exception as e:
            logger.exception("Erro inesperado no worker loop: %s", e)
        finally:
            try:
                queue.task_done()
            except Exception:
                pass


async def orderly_shutdown(bot, timeout: int = 5) -> None:
    try:
        await bot.finalizar()
    except Exception:
        pass


async def main() -> None:
    if AccountingBot is None:
        logger.error("AccountingBot não disponível; verifique executor_motor.py")
        return

    bot = AccountingBot(headless=False, slow_mo=800)
    try:
        await bot.inicializar()
    except Exception:
        logger.exception("Falha inicializando bot")
        return

    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    task = asyncio.create_task(worker(queue, bot))
    try:
        await queue.put("12.345.678/0001-90")
        await queue.join()

        # Send sentinel to stop worker gracefully
        await queue.put(None)
        # wait for worker to finish
        await task
    finally:
        try:
            await orderly_shutdown(bot)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
    except Exception as e:
        logger.exception("Erro na execução: %s", e)


def confirm_rcb(rcb_path: str) -> bool:
    """Confirma recepção do arquivo RCB.

    Retorna True se o arquivo existir, False caso contrário. Usado pelo teste
    orquestrador para validar handoff entre sovereign e integração.
    """
    try:
        p = Path(rcb_path)
        if p.exists():
            logger.info("RCB recebido: %s", str(p))
            return True
        logger.error("RCB não encontrado: %s", str(p))
        return False
    except Exception as e:
        logger.exception("Erro verificando RCB: %s", e)
        return False
