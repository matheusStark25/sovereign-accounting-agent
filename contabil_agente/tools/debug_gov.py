import asyncio
from .executor_motor import AccountingBot


async def main():
    bot = AccountingBot(headless=False)
    await bot.inicializar()
    try:
        ctx = await bot._obter_contexto("GOV_DEBUG")
        page = await ctx.new_page()
        await page.goto(
            "https://www.gov.br/empresas-e-negocios/pt-br/empreendedor",
            wait_until="networkidle",
        )
        print("Navegado para:", page.url)
        print(
            "Abrindo pausa para inspeção manual. Interaja com o navegador e então feche ou continue."
        )
        try:
            await page.pause()
        except Exception:
            pass
    finally:
        await bot.finalizar()


if __name__ == "__main__":
    asyncio.run(main())
