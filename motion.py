"""HTML/CSS/JS motion graphics, rendered frame by frame with headless Chromium (Playwright).

The page (motion_template.html) draws the kinetic title, the glass key-phrase cards and the serif subtitles with the
gliding gold highlight on a TRANSPARENT background. Every frame is a pure function of time, so the result is exactly the
same on every run. main.py lays the PNG sequence over the finished footage with ffmpeg. If anything here fails,
main.py falls back to the classic ASS look.
"""
import asyncio
import json
import math
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "motion_template.html"
W, H = 1080, 1920


def _pick(fonts_dir, *globs):
    for g in globs:
        for p in sorted(Path(fonts_dir).glob(g)):
            if p.suffix.lower() in (".ttf", ".otf"):
                return p
    return None


def _font_css(fonts_dir):
    roles = {
        "MG Display": _pick(fonts_dir, "your_title.*", "Anton*.ttf"),
        "MG Serif": _pick(fonts_dir, "your_subtitle.*", "PlayfairDisplay*.ttf", "Playfair*.ttf"),
        "MG UI": _pick(fonts_dir, "SpaceGrotesk*.ttf"),
    }
    css = []
    for fam, path in roles.items():
        if path:
            css.append(f"@font-face{{font-family:'{fam}';src:url('{path.resolve().as_uri()}');font-weight:100 900;font-style:normal}}")
    return "\n".join(css), {k: (v.name if v else None) for k, v in roles.items()}


def write_page(spec, out_dir, fonts_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    css, used = _font_css(fonts_dir)
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__FONTFACE__*/", css).replace("/*__DATA__*/null", json.dumps(spec))
    page = out_dir / "index.html"
    page.write_text(html, encoding="utf-8")
    return page, used


async def _open_pages(browser, uri, n):
    pages = []
    for _ in range(n):
        pg = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        await pg.goto(uri)
        await pg.wait_for_function("window.__ready===true", timeout=45000)
        err = await pg.evaluate("window.__error||''")
        if err:
            raise RuntimeError("motion page error: " + err)
        pages.append(pg)
    return pages


async def _render(page_file, out_dir, total, fps, workers, log):
    from playwright.async_api import async_playwright

    n = int(math.ceil(total * fps))
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-gpu", "--font-render-hinting=none"])
        try:
            pages = await _open_pages(browser, page_file.resolve().as_uri(), workers)

            async def work(pg, idxs):
                for i in idxs:
                    await pg.evaluate("t => render(t)", i / fps)
                    await pg.screenshot(path=str(out_dir / f"{i:05d}.png"), omit_background=True)

            t0 = time.time()
            await asyncio.gather(*[work(pg, range(k, n, workers)) for k, pg in enumerate(pages)])
            log(f"motion graphics: {n} frames in {time.time() - t0:.0f}s")
        finally:
            await browser.close()
    return n


def render_overlay(spec, out_dir, fonts_dir, log=print, workers=3, fps=30):
    """renders spec -> out_dir/00000.png ...; returns the number of frames"""
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    page, used = write_page(spec, out_dir, fonts_dir)
    log("motion fonts:", used)
    n = asyncio.run(asyncio.wait_for(_render(page, out_dir, spec["total"], fps, workers, log), timeout=14 * 60))
    got = len(list(out_dir.glob("*.png")))
    if got != n:
        raise RuntimeError(f"expected {n} frames, got {got}")
    return n


async def _check(page_file, total, step):
    from playwright.async_api import async_playwright

    problems, shown = [], 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-gpu"])
        try:
            (pg,) = await _open_pages(browser, page_file.resolve().as_uri(), 1)
            t = 0.0
            while t < total:
                rects = await pg.evaluate("t => visibleRects(t)", t)
                shown += 1 if rects else 0
                for r in rects:
                    if r["l"] < 20 or r["r"] > W - 20 or r["t"] < 0 or r["b"] > H:
                        problems.append((round(t, 2), "out of frame", r["k"], [round(r[x]) for x in "ltrb"]))
                for i in range(len(rects)):
                    for j in range(i + 1, len(rects)):
                        a, b = rects[i], rects[j]
                        if a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"]:
                            problems.append((round(t, 2), "overlap", a["k"], b["k"]))
                t += step
        finally:
            await browser.close()
    return problems, shown


def check_layout(spec, out_dir, fonts_dir, step=0.05):
    """dry run, no screenshots: reports any moment where two lanes overlap or something leaves the frame"""
    page, _ = write_page(spec, out_dir, fonts_dir)
    return asyncio.run(_check(page, spec["total"], step))
