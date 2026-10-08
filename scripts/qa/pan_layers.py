"""지도를 조금 옮길 때(드래그 120px) 화면 범위 레이어(시설·은행·약국) 점을 몇 개 새로 만들고 지우는지 — 3회 중앙값.

성능 측정용(통과·실패 판정 없음). 지역은 인자로: python scripts/qa/pan_layers.py 11020
"""
import asyncio
import statistics
import sys

from playwright.async_api import async_playwright

from _common import WEB, launch

ADM = sys.argv[1] if len(sys.argv) > 1 else "37520"

OBS = """() => { window.__added = 0; window.__removed = 0;
  new MutationObserver((ms) => { for (const m of ms) { for (const n of m.addedNodes) if (n.nodeType === 1 && (n.querySelector?.('.fac-dot,.care-dot') || n.classList?.contains('fac-dot') || n.classList?.contains('care-dot'))) window.__added++;
    for (const n of m.removedNodes) if (n.nodeType === 1 && (n.querySelector?.('.fac-dot,.care-dot') || n.classList?.contains('fac-dot') || n.classList?.contains('care-dot'))) window.__removed++; } })
  .observe(document.querySelector('main') || document.body, { childList: true, subtree: true }); }"""

async def once(b):
    pg = await (await b.new_context(viewport={"width": 1440, "height": 900})).new_page()
    await pg.goto(WEB + f"/?adm={ADM}", wait_until="load"); await pg.wait_for_timeout(4000)
    await pg.mouse.move(500, 450)
    for _ in range(3):
        await pg.mouse.wheel(0, -400); await pg.wait_for_timeout(700)
    for label in ["우체국 시설 보기", "은행·금고 지점 보기", "약국·의원 보기"]:
        await pg.get_by_role("checkbox", name=label).first.check(force=True)
    await pg.wait_for_timeout(3000)
    total = await pg.locator(".fac-dot, .care-dot").count()
    await pg.evaluate(OBS)
    t0 = await pg.evaluate("performance.now()")
    await pg.mouse.move(600, 450); await pg.mouse.down(); await pg.mouse.move(720, 450, steps=8); await pg.mouse.up()
    await pg.wait_for_timeout(3000)
    added, removed = await pg.evaluate("[window.__added, window.__removed]")
    after = await pg.locator(".fac-dot, .care-dot").count()
    await pg.context.close()
    return total, after, added, removed

async def main():
    async with async_playwright() as p:
        b = await launch(p)
        runs = [await once(b) for _ in range(3)]
        await b.close()
    for r in runs:
        print("dots before %d after %d | added %d removed %d" % r)
    print("median added", statistics.median(r[2] for r in runs), "removed", statistics.median(r[3] for r in runs))
if __name__ == "__main__":
    asyncio.run(main())
