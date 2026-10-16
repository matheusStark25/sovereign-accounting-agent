"""ToolMEI — Parte 1: inicialização e preenchimento do PGMEI (OOP).

Implementa a Parte 1 conforme solicitado: limpeza de processos, inicialização
do Playwright (headful), navegação direta ao PGMEI, preenchimento do `#cnpj`,
pausa para resolução manual do hCaptcha e validação da URL de saída.

Uso: importar `ToolMEI` e chamar `asyncio.run(tool.parte1(cnpj))` ou executar
o módulo diretamente passando o CNPJ como argumento.
"""

from __future__ import annotations

import asyncio
import os
import sys

try:
    from playwright.async_api import async_playwright
except Exception:
    async_playwright = None  # type: ignore


TARGET_URL = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"


class ToolMEI:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    async def _kill_zombies(self) -> None:
        try:
            os.system("taskkill /f /im chromium.exe /t 2>nul")
        except Exception:
            pass

    async def _start_browser(self) -> None:
        if not async_playwright:
            raise RuntimeError("Playwright não disponível no ambiente")
        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(headless=False)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        self.page = await self._context.new_page()

    async def parte1(self, cnpj: str) -> bool:
        """Executa a Parte 1 conforme protocolo pedido.

        - Navega para o `TARGET_URL`.
        - Preenche `#cnpj` com alta precisão.
        - Aguarda 500ms para processamento da máscara.
        - Pausa e instrui o operador a resolver hCaptcha e clicar CONTINUAR.
        - Após ENTER, valida se a URL contém `/Emitir/` ou `/Consultar/`.
        """

        # 1) Inicialização limpa
        await self._kill_zombies()
        print("[INFO] Motor limpo (zumbis mortos)")

        await self._start_browser()
        print("[INFO] Playwright iniciado (headful, 1280x720)")

        # 2) Navegação e preenchimento
        try:
            await self.page.goto(
                TARGET_URL, wait_until="domcontentloaded", timeout=60000
            )
        except Exception:
            await self.page.goto(
                TARGET_URL, wait_until="domcontentloaded", timeout=120000
            )

        # 2) Sanity check: limpeza e inserção via digitação humana
        # Prefer '#cnpj' mas tente alternativas se não existir
        sel = "#cnpj"
        try:
            if not await self.page.query_selector(sel):
                if await self.page.query_selector("input[name='cnpj']"):
                    sel = "input[name='cnpj']"
                elif await self.page.query_selector("input[id*='cnpj']"):
                    sel = "input[id*='cnpj']"
        except Exception:
            pass

        # Garantir campo limpo via evaluate
        try:
            await self.page.evaluate(
                "(sel) => { const e = document.querySelector(sel); if(e) e.value = ''; }",
                sel,
            )
        except Exception:
            try:
                await self.page.click(sel)
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Delete")
            except Exception:
                pass

        # Digitar com delay humano e verificar valor real
        import re

        attempts = 2
        verified = False
        for attempt in range(attempts):
            try:
                await self.page.click(sel)
                await self.page.type(sel, cnpj, delay=100)
            except Exception:
                try:
                    await self.page.evaluate(
                        "(sel, val) => { const el=document.querySelector(sel); if(el){ el.value=val; el.dispatchEvent(new Event('input',{bubbles:true})); } }",
                        sel,
                        cnpj,
                    )
                except Exception:
                    print("[ERROR] Falha ao inserir CNPJ no campo")
                    return False

            # aguardar máscara processar
            await asyncio.sleep(0.5)

            try:
                valor_real = await self.page.input_value(sel)
            except Exception:
                try:
                    valor_real = await self.page.evaluate(
                        "(sel) => { const e=document.querySelector(sel); return e ? e.value : ''; }",
                        sel,
                    )
                except Exception:
                    valor_real = ""

            apenas_digitos_real = re.sub(r"\D", "", valor_real or "")
            apenas_digitos_esperado = re.sub(r"\D", "", cnpj or "")

            if apenas_digitos_real == apenas_digitos_esperado:
                print(
                    "✅ [VERIFICAÇÃO]: CNPJ validado com sucesso. Integridade de 100%."
                )

                # Detectar se o campo com '#cnpj' está em outra aba/page do contexto
                try:
                    page_with_sel = None
                    for p in self._context.pages if self._context else []:
                        try:
                            if await p.query_selector(sel):
                                page_with_sel = p
                                break
                        except Exception:
                            continue

                    # Se encontramos uma aba diferente, trazê-la para frente
                    if page_with_sel and page_with_sel != self.page:
                        try:
                            await page_with_sel.bring_to_front()
                            self.page = page_with_sel
                            print("[INFO] Nova aba detectada e trazida para frente.")
                        except Exception as e:
                            print(f"[DEBUG] Falha ao trazer nova aba para frente: {e}")

                    # screenshot do elemento para auditoria na aba atual (onde está o campo)
                    try:
                        el = await self.page.query_selector(sel)
                        if el:
                            out_aud = os.path.join(os.getcwd(), "auditoria_cnpj.png")
                            try:
                                if not getattr(self.page, "is_closed", lambda: False)():
                                    await el.screenshot(path=out_aud)
                                    print(
                                        f"[DEBUG] Auditoria screenshot salvo: {out_aud}"
                                    )
                                else:
                                    print(
                                        "[DEBUG] Página fechada antes da auditoria; pulando screenshot de elemento"
                                    )
                            except Exception as se:
                                print(
                                    f"[DEBUG] Falha ao salvar auditoria (elemento): {se}"
                                )
                        else:
                            # fallback: screenshot full page of the current (focused) tab
                            out_aud = os.path.join(os.getcwd(), "auditoria_cnpj.png")
                            try:
                                if not getattr(self.page, "is_closed", lambda: False)():
                                    await self.page.screenshot(
                                        path=out_aud, full_page=False
                                    )
                                    print(
                                        f"[DEBUG] Auditoria screenshot (full page) salvo: {out_aud}"
                                    )
                                else:
                                    print(
                                        "[DEBUG] Página fechada antes da auditoria; pulando screenshot full page"
                                    )
                            except Exception as se:
                                print(
                                    f"[DEBUG] Falha ao salvar auditoria (full page): {se}"
                                )
                    except Exception as e:
                        print(f"[DEBUG] Falha ao salvar auditoria: {e}")

                except Exception:
                    pass

                verified = True
                break
            else:
                print(
                    f"❌ [ERRO CRÍTICO]: Divergência detectada! Esperado: {cnpj} | Encontrado: {valor_real}."
                )
                # limpar e tentar novamente
                try:
                    await self.page.evaluate(
                        "(sel) => { const e=document.querySelector(sel); if(e) e.value = ''; }",
                        sel,
                    )
                except Exception:
                    try:
                        await self.page.click(sel)
                        await self.page.keyboard.press("Control+A")
                        await self.page.keyboard.press("Delete")
                    except Exception:
                        pass
                if attempt == attempts - 1:
                    print(
                        "[ERROR] Tentativas esgotadas. Abortando Parte1 para evitar perda de tempo."
                    )
                    # fechar recursos limpo
                    try:
                        if self._context:
                            await self._context.close()
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
                    return False

        if not verified:
            return False

        # 3) Protocolo de pausa para hCaptcha (printed instructions)
        separator = "------------------------------------------------------------"
        print(separator)
        print("🚨 ALVO LOCALIZADO: CNPJ PREENCHIDO.")
        print("👉 AÇÃO: Resolva o hCaptcha manualmente e clique em CONTINUAR.")
        print("👉 APÓS a página de débitos carregar, pressione ENTER aqui.")
        print(separator)

        # Wait for operator to press ENTER without blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)

        # 4) Após ENTER: coletar diagnósticos e validar URL de saída
        try:
            # captura screenshot e trecho de HTML para diagnóstico
            try:
                out_png = os.path.join(os.getcwd(), "parte1_after_enter.png")
                if not getattr(self.page, "is_closed", lambda: False)():
                    await self.page.screenshot(path=out_png, full_page=True)
                    print(f"[DEBUG] Screenshot salvo: {out_png}")
                else:
                    print(
                        "[DEBUG] Página fechada antes do screenshot after_enter; pulando"
                    )
            except Exception as e:
                print(f"[DEBUG] Falha ao salvar screenshot: {e}")

            try:
                html = await self.page.content()
                trimmed = html[:2000]
                out_html = os.path.join(os.getcwd(), "parte1_after_enter.html")
                with open(out_html, "w", encoding="utf-8") as f:
                    f.write(trimmed)
                print(f"[DEBUG] HTML (trecho) salvo: {out_html}")
            except Exception as e:
                print(f"[DEBUG] Falha ao salvar HTML: {e}")

            try:
                title = await self.page.title()
            except Exception:
                title = ""

            try:
                current = self.page.url or ""
            except Exception:
                try:
                    current = await self.page.evaluate("() => window.location.hre")
                except Exception:
                    current = ""

            print(f"[DEBUG] URL atual: {current}")
            print(f"[DEBUG] Título da página: {title}")

            if "/Emitir/" in current or "/Consultar/" in current:
                print("[SUCESSO] | Parte 1 Vencida. Estamos dentro do sistema.")
                return True
            else:
                print("[ALERTA] | Ainda na página de identificação. Verifique o erro.")
                return False
        finally:
            # Fechar recursos limpo para evitar warnings do asyncio
            try:
                if self._context:
                    await self._context.close()
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
            # pequena espera para flush de transportes
            try:
                await asyncio.sleep(0.1)
            except Exception:
                pass


def _cli_main():
    if len(sys.argv) < 2:
        print("Usage: python mei_tool.py <CNPJ>")
        return
    cnpj = sys.argv[1]
    tool = ToolMEI()
    try:
        res = asyncio.run(tool.parte1(cnpj))
        print("Resultado Parte1:", res)
    except KeyboardInterrupt:
        print("Interrompido pelo usuário")


if __name__ == "__main__":
    _cli_main()
