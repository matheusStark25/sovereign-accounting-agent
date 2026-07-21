import asyncio
import sys

try:
    from playwright.async_api import async_playwright
except Exception:
    print("Playwright not available. Activate venv with Playwright installed.")
    raise


async def map_page(url: str, out_png: str = "mapa_da_pagina.png") -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768}, ignore_https_errors=True
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            except Exception as e:
                print(f"Failed to goto {url}: {e}")
                return 2

        # wait stabilization
        await asyncio.sleep(5)

        # take screenshot
        try:
            await page.screenshot(path=out_png, full_page=True)
            print(f"[MAPA]: screenshot saved -> {out_png}")
        except Exception as e:
            print(f"[MAPA]: failed to save screenshot: {e}")

        script = r"""
        (() => {
            const out = {elements: [], frames: []};
            function describe(el){
                try{
                    return {
                        tag: el.tagName,
                        text: (el.innerText||el.textContent||"").trim().slice(0,200),
                        id: el.id||null,
                        class: el.className||null,
                        name: el.getAttribute && el.getAttribute('name') || null,
                        placeholder: el.getAttribute && el.getAttribute('placeholder') || null,
                        type: el.getAttribute && el.getAttribute('type') || null,
                        visible: (el.offsetParent !== null) || (window.getComputedStyle(el).visibility !== 'hidden')
                    };
                } catch(e){ return {error: String(e)}; }
            }

            const inputs = Array.from(document.querySelectorAll('input, textarea, button, a'));
            for(let i=0;i<inputs.length;i++){
                out.elements.push(describe(inputs[i]));
            }

            const iframes = Array.from(document.querySelectorAll('iframe'));
            for(let i=0;i<iframes.length;i++){
                const f = iframes[i];
                out.frames.push({id: f.id||null, name: f.name||null, src: f.src||null});
            }

            return out;
        })();
        """

        try:
            result = await page.evaluate(script)
        except Exception as e:
            print(f"[MAPA]: evaluate failed: {e}")
            result = None

        if result:
            elements = result.get("elements", [])
            for idx, el in enumerate(elements, start=1):
                txt = el.get("text") or ""
                print(
                    f"[MAPA]: Elemento {idx}: tag='{el.get('tag')}' | "
                    f"ID='{el.get('id')}' | Nome='{el.get('name')}' | "
                    f"Classe='{el.get('class')}' | Placeholder='{el.get('placeholder')}' | "
                    f"Texto='{txt}' | Visivel='{el.get('visible')}'"
                )

            frames = result.get("frames", [])
            if frames:
                for i, f in enumerate(frames, start=1):
                    print(
                        f"[MAPA]: Frame {i}: id='{f.get('id')}' | name='{f.get('name')}' | src='{f.get('src')}'"
                    )
            else:
                print("[MAPA]: No frames detected")

        # do not close browser per instruction; keep it open for manual inspection
        print("[MAPA]: Mapping complete — browser left open for inspection.")
        return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python mapa_pgmei.py <URL> [out_png]")
        print(
            "Example: python mapa_pgmei.py https://www.gov.br/pt-br mapa_da_pagina.png"
        )
        return
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "mapa_da_pagina.png"
    sys.exit(asyncio.run(map_page(url, out)))


if __name__ == "__main__":
    main()
