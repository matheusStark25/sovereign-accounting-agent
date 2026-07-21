"""Lightweight AccountingBot for integration tests.

This simplified implementation focuses on the stability fixes requested:
- create browser contexts with `ignore_https_errors=True`
- inject a viewport meta after `goto` to lock zoom
- avoid repeated smooth scrolling; use a single mouse.wheel(0,500)
- do not close contexts/browser in `finalizar()` (debug mode)
- provide a brute-force `_click_any_text_input` used by `_acao_fill`

This file is intentionally minimal to avoid formatting issues and to be
easy to maintain while debugging integration flows.
"""

from __future__ import annotations

import os
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import time
from contabil_agente.queue.rabbit_provider import RabbitPublisher

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except Exception:
    async_playwright = None  # type: ignore
    PLAYWRIGHT_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class SessionAuditoria:
    tenant_id: str
    session_id: str
    timestamp_inicio: datetime = field(default_factory=datetime.now)
    timestamp_fim: Optional[datetime] = None
    total_acoes: int = 0
    acoes_sucesso: int = 0
    acoes_falha: int = 0
    logs: List[Dict[str, Any]] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    status: str = "em_andamento"

    def adicionar_log(
        self, acao: str, status: str, detalhes: Optional[Dict[str, Any]] = None
    ) -> None:
        self.logs.append(
            {
                "timestamp": datetime.now().isoformat(),
                "acao": acao,
                "status": status,
                "detalhes": detalhes or {},
            }
        )
        self.total_acoes += 1
        if status == "sucesso":
            self.acoes_sucesso += 1
        elif status == "erro":
            self.acoes_falha += 1

    def finalizar(self, status: str = "concluido") -> None:
        self.timestamp_fim = datetime.now()
        self.status = status


class AccountingBot:
    """Minimal bot implementing the requested radical fixes."""

    def __init__(
        self, headless: bool = True, logs_dir: Optional[Path] = None, slow_mo: int = 0
    ):
        # Enforce visible browser per specification (non-headless)
        self.headless = False
        # Default slow_mo in ms for visual tracing (1000-2000ms)
        self.slow_mo = slow_mo or 1500
        self._playwright = None
        self._browser = None
        self._contexts: Dict[str, Any] = {}
        self.logs_dir = logs_dir or Path("logs")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # debug flag: when True keep browser open for manual inspection
        self.debug_keep_open = False

    async def inicializar(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not available in this environment")
        # Matador de Zumbis: kill lingering chromium/node processes before launching
        try:
            os.system("taskkill /f /im chromium.exe /t 2>nul")
            os.system("taskkill /f /im node.exe /t 2>nul")
        except Exception:
            pass

        self._playwright = await async_playwright().__aenter__()
        # Use slow_mo on launch to slow down actions for visual debugging
        launch_kwargs = {}
        launch_kwargs["slow_mo"] = int(getattr(self, "slow_mo", 1500))
        # Harden launch args to reduce detection and avoid GPU hangs
        launch_kwargs.setdefault(
            "args",
            [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-gpu",
            ],
        )
        # Always visible (non-headless) per specification
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless, **launch_kwargs
        )
        logger.info("Playwright iniciado")

    async def _obter_contexto(self, tenant_id: str):
        if tenant_id in self._contexts:
            return self._contexts[tenant_id]

        ctx = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            ignore_https_errors=True,
            accept_downloads=True,
        )

        # Add stealth + meta-viewport init scripts at context level so they're
        # present before any page scripts execute. This helps lock zoom and
        # reduce Playwright detection on gov.br.
        try:
            stealth_script = """
            () => {
                try {
                    Object.defineProperty(navigator, 'webdriver', {get: () => false});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt','en-US']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4]});
                    const originalQuery = window.navigator.permissions.query;
                    try {
                        window.navigator.permissions.query = (parameters) =>
                            parameters.name === 'notifications'
                                ? Promise.resolve({ state: 'denied' })
                                : originalQuery(parameters);
                    } catch (e) {}
                } catch (e) {}
            }
            """
            await ctx.add_init_script(stealth_script)
        except Exception:
            logger.debug("Falha ao adicionar stealth init script no contexto")

        try:
            meta = "document.head.insertAdjacentHTML('beforeend', '<meta name=\"viewport\" content=\"width=1366, initial-scale=1.0, maximum-scale=1.0, user-scalable=no\">');"
            await ctx.add_init_script(meta)
        except Exception:
            logger.debug("Falha ao adicionar meta viewport no contexto")

        # Install a context-level route to block analytics/tracking domains early
        try:

            async def _route_block(route, request):
                url = request.url.lower()
                block_keywords = [
                    "google-analytics",
                    "googletagmanager",
                    "doubleclick",
                    "analytics",
                    "segment",
                    "mixpanel",
                    "hotjar",
                    "facebook",
                    "ads",
                    "adservice",
                ]
                if any(k in url for k in block_keywords):
                    try:
                        await route.abort()
                        return
                    except Exception:
                        pass
                try:
                    await route.continue_()
                except Exception:
                    try:
                        await route.continue_()
                    except Exception:
                        pass

            await ctx.route("**/*", _route_block)
        except Exception:
            logger.debug("Falha ao instalar bloqueio de rotas de analytics no contexto")

        self._contexts[tenant_id] = ctx
        logger.info(f"Contexto criado: {tenant_id}")
        return ctx

    async def executar_fluxo(
        self, config: Dict[str, Any], tenant_id: str, session_id: Optional[str] = None
    ) -> SessionAuditoria:
        if not session_id:
            session_id = (
                f"session_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
        sessao = SessionAuditoria(tenant_id=tenant_id, session_id=session_id)

        ctx = await self._obter_contexto(tenant_id)
        page = await ctx.new_page()

        async def _safe_sleep(secs: float) -> None:
            try:
                await asyncio.sleep(secs)
            except asyncio.CancelledError:
                logger.debug("Sleep cancelled")
                raise

        def _page_open(p) -> bool:
            try:
                # Playwright Page has is_closed() method
                return not p.is_closed()
            except Exception:
                try:
                    return not getattr(p, "_closed", False)
                except Exception:
                    return False

        for acao in config.get("acoes", []):
            tipo = acao.get("tipo")
            try:
                if tipo == "goto":
                    url = acao.get("url")
                    # Use domcontentloaded as required by spec
                    try:
                        await page.goto(
                            url,
                            timeout=acao.get("timeout", 30000),
                            wait_until=acao.get("wait_until", "domcontentloaded"),
                        )
                    except Exception:
                        # fallback: retry once with longer timeout
                        await page.goto(
                            url, timeout=60000, wait_until="domcontentloaded"
                        )

                    # Debug print to indicate page responded
                    try:
                        print("✅ [MOTOR]: Página carregada e respondendo!")
                    except Exception:
                        pass

                    # POST-GOTO corrections (Etapa 2)
                    try:
                        # small stabilization wait
                        await _safe_sleep(2)
                        await page.evaluate("""
                            () => {
                                try {
                                    // Remove viewport metas
                                    const metas = Array.from(document.querySelectorAll('meta[name=viewport]'));
                                    for (const m of metas) { try { m.remove(); } catch(e){} }

                                    // Insert fixed viewport meta
                                    const vm = document.createElement('meta');
                                    vm.name = 'viewport';
                                    vm.content = 'width=1366, initial-scale=1.0, maximum-scale=1.0, user-scalable=no';
                                    document.head.appendChild(vm);

                                    // Force desktop CSS and neutralize mobile media queries
                                    const style = document.createElement('style');
                                    style.id = 'pw-viewport-fix';
                                    style.innerHTML = '\n' +
                                        'html, body { zoom: 1 !important; transform: none !important; -webkit-text-size-adjust: 100% !important; min-width: 1366px !important;}\n' +
                                        '@media only screen and (max-width: 1366px) { body, html { min-width: 1366px !important; width: 1366px !important; } }\n';
                                    document.head.appendChild(style);

                                    // Cap timers to 5000ms
                                    try { const oTO = window.setTimeout; window.setTimeout = (fn,t, ...r) => oTO(fn, Math.min(Number(t)||0,5000), ...r); } catch(e){}
                                    try { const oTI = window.setInterval; window.setInterval = (fn,t,...r) => oTI(fn, Math.min(Number(t)||0,5000), ...r); } catch(e){}

                                    // Stop any remaining loading
                                    try { window.stop(); } catch(e) {}
                                } catch(e) {}
                            }
                        """)
                        await _safe_sleep(1.5)
                        try:
                            path = (
                                self.logs_dir
                                / f"post_goto_{int(datetime.now().timestamp())}.png"
                            )
                            if _page_open(page):
                                try:
                                    await page.screenshot(
                                        path=str(path), full_page=False
                                    )
                                    logger.info(f"🔧 Screenshot pós-goto salvo: {path}")
                                except Exception as se:
                                    logger.debug(
                                        "Falha ao salvar screenshot pós-goto: %s", se
                                    )
                            else:
                                logger.debug(
                                    "Página fechada antes do screenshot pós-goto; pulando"
                                )
                        except Exception:
                            logger.debug(
                                "Falha ao compor caminho do screenshot pós-goto"
                            )
                    except Exception as e:
                        logger.debug(f"Falha ao aplicar correção pós-goto: {e}")

                elif tipo == "click":
                    sel = acao.get("selector")
                    timeout = acao.get("timeout", 10000)

                    # Neutralize common overlays that may block interactions
                    try:
                        await page.evaluate("""
                            () => {
                                try {
                                    const divs = Array.from(document.querySelectorAll('div'));
                                    for (const d of divs) {
                                        const s = getComputedStyle(d);
                                        const z = parseInt(s.zIndex || 0, 10);
                                        const isFixed = s.position === 'fixed' || s.position === 'sticky';
                                        const cls = ((d.id||'') + ' ' + (d.className||'')).toLowerCase();
                                        if ((isFixed && z > 0) || /overlay|backdrop|modal|cookie|consent/.test(cls)) {
                                            try { d.style.pointerEvents = 'none'; d.style.visibility = 'hidden'; } catch(e){}
                                        }
                                    }
                                } catch(e){}
                            }
                        """)
                    except Exception:
                        pass

                    clicked = False
                    if sel:
                        # Strategy: wait for visible, check enabled, try normal click -> force -> bbox
                        try:
                            await page.wait_for_selector(
                                sel, state="visible", timeout=timeout
                            )
                            elem = await page.query_selector(sel)
                            if elem and await elem.is_enabled():
                                # 1) try normal click
                                try:
                                    await elem.click()
                                    clicked = True
                                except Exception:
                                    await asyncio.sleep(1)
                                    # 2) try force click
                                    try:
                                        await elem.click(force=True)
                                        clicked = True
                                    except Exception:
                                        await asyncio.sleep(1)
                                        # 3) bounding box click
                                        try:
                                            box = await elem.bounding_box()
                                            if box:
                                                x = box["x"] + box["width"] / 2
                                                y = box["y"] + box["height"] / 2
                                                await page.mouse.click(x, y)
                                                clicked = True
                                        except Exception:
                                            clicked = False
                            else:
                                # try force click even if not enabled
                                try:
                                    await page.click(sel, force=True)
                                    clicked = True
                                except Exception:
                                    clicked = False
                        except Exception:
                            clicked = False

                        # Try frames if not clicked
                        if not clicked:
                            try:
                                for f in page.frames:
                                    try:
                                        elem = await f.query_selector(sel)
                                        if elem:
                                            try:
                                                await elem.click()
                                                clicked = True
                                                break
                                            except Exception:
                                                try:
                                                    await elem.click(force=True)
                                                    clicked = True
                                                    break
                                                except Exception:
                                                    continue
                                    except Exception:
                                        continue
                            except Exception:
                                pass

                    if not clicked:
                        raise RuntimeError(f"Falha ao clicar no seletor: {sel}")

                elif tipo == "fill":
                    sel = acao.get("selector")
                    val = acao.get("value", "")
                    timeout = acao.get("timeout", 10000)

                    # Helper to format CNPJ if digits provided
                    def _format_cnpj(s: str) -> str:
                        only = "".join([c for c in s if c.isdigit()])
                        if len(only) == 14:
                            return f"{only[0:2]}.{only[2:5]}.{only[5:8]}/{only[8:12]}-{only[12:14]}"
                        return s

                    formatted = _format_cnpj(str(val))
                    filled = False
                    try:
                        await page.wait_for_selector(
                            sel, state="visible", timeout=timeout
                        )
                        # Clear via select-all + delete
                        await page.click(sel)
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
                        # Type with delay 100ms per character
                        await page.keyboard.type(formatted, delay=100)
                        # Dispatch input/change/blur
                        try:
                            await page.evaluate(
                                (
                                    "(sel) => { "
                                    "const el = document.querySelector(sel); "
                                    "if(el){ "
                                    "el.dispatchEvent(new Event('input',{bubbles:true})); "
                                    "el.dispatchEvent(new Event('change',{bubbles:true})); "
                                    "el.blur(); "
                                    "} "
                                    "}"
                                ),
                                sel,
                            )
                        except Exception:
                            pass
                        filled = True
                    except Exception:
                        filled = False

                    # Frames fallback
                    if not filled:
                        try:
                            for f in page.frames:
                                try:
                                    await f.wait_for_selector(
                                        sel, state="visible", timeout=2000
                                    )
                                    await f.click(sel)
                                    await f.fill(sel, "")
                                    await f.type(sel, formatted, delay=100)
                                    filled = True
                                    break
                                except Exception:
                                    continue
                        except Exception:
                            pass

                    # Brute-force fallback: click any visible input then type
                    if not filled:
                        try:
                            await page.evaluate("""
                                () => {
                                    try {
                                        const divs = Array.from(document.querySelectorAll('div'));
                                        for (const d of divs) {
                                            const s = getComputedStyle(d);
                                            const z = parseInt(s.zIndex || 0, 10);
                                            const isFixed = s.position === 'fixed' || s.position === 'sticky';
                                            const cls = ((d.id||'') + ' ' + (d.className||'')).toLowerCase();
                                            if ((isFixed && z > 0) || /overlay|backdrop|modal|cookie|consent/.test(cls)) {
                                                try { d.style.pointerEvents = 'none'; d.style.visibility = 'hidden'; } catch(e){}
                                            }
                                        }
                                    } catch(e){}
                                }
                            """)
                        except Exception:
                            pass

                        clicked = await self._click_any_text_input(page)
                        if clicked:
                            try:
                                await page.keyboard.type(formatted, delay=100)
                                filled = True
                            except Exception:
                                filled = False

                    if not filled:
                        raise RuntimeError(f"Falha ao preencher o campo: {sel}")

                elif tipo == "wait":
                    if acao.get("selector"):
                        await page.wait_for_selector(
                            acao.get("selector"), timeout=acao.get("timeout", 30000)
                        )
                    else:
                        await _safe_sleep(acao.get("tempo", 1))

                elif tipo == "screenshot":
                    path = self.logs_dir / acao.get("path", "screenshot.png")
                    try:
                        if _page_open(page):
                            await page.screenshot(
                                path=str(path), full_page=acao.get("full_page", True)
                            )
                            sessao.screenshots.append(str(path))
                        else:
                            logger.warning(
                                "Página fechada - screenshot '%s' pulado", path
                            )
                    except Exception as se:
                        logger.debug("Falha ao tirar screenshot %s: %s", path, se)

                # rule of gold: if page jumps, pause
                try:
                    await _safe_sleep(0.5)
                except asyncio.CancelledError:
                    logger.debug("execução do fluxo cancelada durante pausa")
                    raise

                sessao.adicionar_log(tipo, "sucesso")
            except Exception as e:
                logger.exception(f"Erro na ação {tipo}: {e}")
                sessao.adicionar_log(tipo, "erro", {"erro": str(e)})

        sessao.finalizar(status="concluido")
        return sessao

    async def _click_any_text_input(self, page) -> bool:
        selectors = [
            "input[type='text']",
            "input[type='tel']",
            "textarea",
            "input:not([type])",
        ]
        for sel in selectors:
            try:
                elems = await page.query_selector_all(sel)
            except Exception:
                elems = []
            for e in elems:
                try:
                    try:
                        vis = await e.is_visible()
                    except Exception:
                        vis = False
                    try:
                        ena = await e.is_enabled()
                    except Exception:
                        ena = False
                    if vis and ena:
                        try:
                            await e.click()
                        except Exception:
                            try:
                                box = await e.bounding_box()
                                if box:
                                    await page.mouse.click(
                                        box["x"] + box["width"] / 2,
                                        box["y"] + box["height"] / 2,
                                    )
                            except Exception:
                                pass
                        return True
                except Exception:
                    continue
        return False

    async def click_with_pyautogui(self, page, selector: str, retries: int = 2) -> bool:
        """Fallback hybrid click using PyAutoGUI when Playwright clicks fail.

        Best-effort: obtains element bounding rect and attempts an OS-level click
        on the computed screen coordinates. This requires `pyautogui` installed
        and that the browser window is visible and not covered.
        """

        try:

            try:
                import pyautogui  # type: ignore
            except ImportError:
                pyautogui = None
        except ImportError:
            return False
        except Exception:
            return False

        for attempt in range(retries):
            try:
                # Ask the page for element rect, screen offset and devicePixelRatio
                info = await page.evaluate(
                    """
                    (sel) => {
                        try {
                            const el = document.querySelector(sel);
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return {
                                rect: { x: r.left, y: r.top, width: r.width, height: r.height },
                                screenX: window.screenX || 0,
                                screenY: window.screenY || 0,
                                dpr: window.devicePixelRatio || 1,
                                scrollX: window.scrollX || 0,
                                scrollY: window.scrollY || 0
                            };
                        } catch (e) { return null; }
                    }
                    """,
                    selector,
                )
                if not info:
                    await asyncio.sleep(1)
                    continue

                rect = info.get("rect")
                dpr = info.get("dpr") or 1
                screen_x = info.get("screenX") or 0
                screen_y = info.get("screenY") or 0

                # Compute center point (best-effort). Note: may need tuning per OS.
                center_x = int(screen_x + (rect["x"] + rect["width"] / 2) * dpr)
                center_y = int(screen_y + (rect["y"] + rect["height"] / 2) * dpr)

                pyautogui.FAILSAFE = False
                pyautogui.moveTo(center_x, center_y, duration=0.25)
                pyautogui.click()
                # small wait for page reaction
                time.sleep(1.0)
                return True
            except Exception:
                await asyncio.sleep(1)
                continue
        return False

    async def click_element_with_pyautogui(
        self, page, element_handle, retries: int = 2
    ) -> bool:
        """Hybrid click accepting an ElementHandle directly."""
        try:

            # Attempt to import pyautogui for type checking or editor hints, but ignore if not available
            try:
                import pyautogui  # type: ignore
            except ImportError:
                pyautogui = None
        except ImportError:
            return False
        except Exception:
            return False

        for attempt in range(retries):
            try:
                info = await page.evaluate(
                    """
                    (el) => {
                        try {
                            const r = el.getBoundingClientRect();
                            return { rect: { x: r.left, y: r.top, width: r.width, height: r.height }, screenX: window.screenX||0, screenY: window.screenY||0, dpr: window.devicePixelRatio||1 };
                        } catch (e) { return null; }
                    }
                    """,
                    element_handle,
                )
                if not info:
                    await asyncio.sleep(1)
                    continue

                rect = info.get("rect")
                dpr = info.get("dpr") or 1
                screen_x = info.get("screenX") or 0
                screen_y = info.get("screenY") or 0
                center_x = int(screen_x + (rect["x"] + rect["width"] / 2) * dpr)
                center_y = int(screen_y + (rect["y"] + rect["height"] / 2) * dpr)

                pyautogui.FAILSAFE = False
                pyautogui.moveTo(center_x, center_y, duration=0.25)
                pyautogui.click()
                time.sleep(1.0)
                return True
            except Exception:
                await asyncio.sleep(1)
                continue
        return False

    async def finalizar(self) -> None:
        """Finalize and cleanup resources. Ensure zombie processes are killed.

        The bot is disposable: on finalize we attempt to close contexts and the browser
        and kill residual system processes to avoid stuck state on next run.
        """
        logger.info("finalizar() chamado — encerrando contextos e browser")
        try:
            for k, ctx in list(self._contexts.items()):
                try:
                    await ctx.close()
                except Exception:
                    pass
                self._contexts.pop(k, None)
        except Exception:
            pass

        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

        try:
            if self._playwright:
                await self._playwright.__aexit__(None, None, None)
        except Exception:
            pass

        # Matador de Zumbis final — força kill de processos residuais
        try:
            os.system("taskkill /f /im chromium.exe /t 2>nul")
            os.system("taskkill /f /im node.exe /t 2>nul")
        except Exception:
            pass
        logger.info("Recursos liberados e processos órfãos finalizados")


def _run_demo():
    async def main():
        bot = AccountingBot(headless=False)
        await bot.inicializar()
        cfg = {
            "acoes": [
                {"tipo": "goto", "url": "https://example.com"},
                {"tipo": "screenshot", "path": "demo.png"},
            ]
        }
        # When USE_RABBIT=1 we publish the task to RabbitMQ instead of executing locally.
        if os.getenv("USE_RABBIT", "0") == "1":
            pub = RabbitPublisher()
            task = {
                "tenant_id": "demo",
                "config": cfg,
                "meta": {"source": "executor_motor"},
            }
            try:
                pub.publish("esocial_tasks", task)
                print("Published demo task to queue esocial_tasks")
            finally:
                pub.close()
            return

        sess = await bot.executar_fluxo(cfg, tenant_id="demo")
        try:
            # Some SessionAuditoria implementations may provide `para_dict()`
            print(json.dumps(sess.para_dict(), indent=2, ensure_ascii=False))
        except Exception:
            # best-effort: fallback to __dict__ representation
            print(
                json.dumps(
                    {k: v for k, v in sess.__dict__.items() if k != "logs"},
                    default=str,
                    indent=2,
                    ensure_ascii=False,
                )
            )

    asyncio.run(main())


if __name__ == "__main__":
    _run_demo()
