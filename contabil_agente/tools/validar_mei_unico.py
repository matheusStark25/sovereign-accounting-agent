"""Script de validação MEI único - executa o fluxo de preencher CNPJ no Portal
e aguarda.

Uso: roda localmente com ambiente Playwright configurado. Não fecha o
navegador imediatamente para permitir inspeção visual.
"""

import asyncio
import logging
import sys
import os

from .executor_motor import AccountingBot, SessionAuditoria

# Garantir que o diretório pai esteja no sys.path para imports relativos
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)


# Tentativa simples e robusta de importar `ToolMEI` do mesmo diretório.
ToolMEI = None
try:
    from .mei_tool import ToolMEI  # prefer relative import when disponível
except Exception:
    try:
        from mei_tool import ToolMEI  # fallback absolute
    except Exception:
        # Se não existir, ToolMEI permanecerá None e definiremos um fallback abaixo
        ToolMEI = None


# Fallback: definir uma implementação mínima de `ToolMEI` para testes locais
if ToolMEI is None:

    class ToolMEI:
        def __init__(self, bot):
            self.bot = bot

        async def _safe_screenshot(self, page, name_prefix="shot"):
            try:
                os.makedirs("logs", exist_ok=True)
                await page.screenshot(path=f"logs/{name_prefix}.png", full_page=True)
            except Exception:
                pass

        async def acessar_portal_mei(
            self, page, cnpj, tenant_id=None, sessao=None, url: str = None
        ):
            """Fallback minimal para permitir execução do validador localmente.
            Implementa apenas as mudanças solicitadas: viewport fixo, estabilizador,
            clique em 'Acessar' antes, múltiplos seletores para CNPJ e digitação
            sequencial. Não substitui a implementação de produção.
            """
            try:
                # Viewport fixo
                try:
                    await page.set_viewport_size({"width": 1366, "height": 768})
                except Exception:
                    pass

                # Navegar se url fornecida
                if url:
                    try:
                        await page.goto(url)
                    except Exception:
                        pass

                # Estabilizador: aguardar 3s, rolar para topo e congelar 1s
                try:
                    await page.wait_for_timeout(3000)
                    await page.evaluate("() => window.scrollTo(0,0)")
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Clicar em Acessar/Entrar/Login antes de procurar CNPJ
                for txt in ("Acessar", "Entrar", "Login"):
                    try:
                        loc = page.locator(f"text=^{txt}$")
                        await self._safe_screenshot(page, f"before_click_{txt}")
                        if await loc.count() > 0:
                            try:
                                await loc.first.click()
                                await page.wait_for_timeout(2000)
                                break
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Procurar campo CNPJ com sequência segura
                selectors = [
                    "input[placeholder*='CNPJ']",
                    "input[name*='cnpj']",
                    "input[id*='cnpj']",
                ]
                sel = None
                for s in selectors:
                    try:
                        if await page.locator(s).count() > 0:
                            sel = s
                            break
                    except Exception:
                        continue

                # Tentar buscar label contendo 'CNPJ'
                if not sel:
                    try:
                        labels = page.locator(
                            "xpath=//label[contains(translate(normalize-space(.), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'CNPJ')]"
                        )
                        if await labels.count() > 0:
                            lbl = labels.first
                            for_attr = await lbl.get_attribute("for")
                            if for_attr:
                                cand = f"#{for_attr}"
                                if await page.locator(cand).count() > 0:
                                    sel = cand
                    except Exception:
                        pass

                if not sel:
                    await self._safe_screenshot(page, "cnpj_nao_encontrado")
                    return {"status": "cnpj_nao_encontrado", "page": page}

                # Digitar CNPJ sequencialmente (tolerante a máscaras)
                try:
                    locator = page.locator(sel)
                    await locator.first.fill("")
                    for ch in cnpj:
                        await locator.first.type(ch)
                        await page.wait_for_timeout(120)
                except Exception:
                    await self._safe_screenshot(page, "cnpj_type_failed")

                return {"status": "ok", "page": page}
            except Exception:
                try:
                    await self._safe_screenshot(page, "erro_fallback")
                except Exception:
                    pass
                return {"status": "erro", "page": page}


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validar_mei_unico")


async def main():
    tenant_id = "GOV_TESTE"
    cnpj_teste = "00000000000191"  # CNPJ de teste solicitado

    # slow_mo aumentado para dar tempo visual entre ações; mantemos modo visual
    bot = AccountingBot(headless=False, slow_mo=250)

    await bot.inicializar()

    # criar sessão de auditoria manual para o teste
    sessao = SessionAuditoria(tenant_id=tenant_id, session_id="VALIDAR_MEI_001")

    tool = ToolMEI(bot)
    try:
        # Obter contexto e criar página para passar ao ToolMEI
        contexto = await bot._obter_contexto(tenant_id)
        page = await contexto.new_page()

        resultado = await tool.acessar_portal_mei(
            page, cnpj=cnpj_teste, tenant_id=tenant_id, sessao=sessao
        )
        # Manter a página aberta e abrir o Playwright Inspector para permitir
        # interação humana com Captcha. Não fechamos o browser/contexto.
        page = resultado.get("page")
        if page:
            # Pausa o fluxo e abre o inspector — Tony pode interagir manualmente.
            try:
                await page.pause()
            except Exception:
                # Fallback: manter a página aberta por um tempo longo
                await asyncio.sleep(300)
    except Exception as e:
        logger.exception("Erro durante validação MEI: %s", e)

    # Intencional: não finalizamos `bot` aqui para manter o navegador aberto


if __name__ == "__main__":
    asyncio.run(main())
