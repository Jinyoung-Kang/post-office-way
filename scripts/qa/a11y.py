"""접근성(axe-core, WCAG 2.1 AA + 모범 사례) 9개 화면 + 모바일 375px 가로 넘침.

axe-core 는 web/node_modules (devDependency) 에서 읽습니다 — cd web && npm ci.
지도 타일 영역(카카오 SDK 가 그리는 부분)은 우리가 고칠 수 없어 검사에서 뺍니다.
"""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

from _common import PAGES, ROOT, WEB, launch, report

AXE_PATH = ROOT / "web/node_modules/axe-core/axe.min.js"
RUN = """async () => { const r = await axe.run(document, {
  runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']},
  exclude: [['div.bg-\\\\[\\\\#e8e8ed\\\\] > div']] });
  return r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length,
    sample: v.nodes.slice(0, 2).map(n => n.target.join(' '))})) }"""


async def main() -> None:
    if not AXE_PATH.exists():
        sys.exit(f"{AXE_PATH} 없음 — cd web && npm ci")
    axe = AXE_PATH.read_text()
    problems: list[str] = []
    async with async_playwright() as p:
        b = await launch(p)
        desk = await b.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
        pg = await desk.new_page()
        for u in PAGES:
            await pg.goto(WEB + u, wait_until="networkidle"); await pg.wait_for_timeout(2500)
            await pg.add_script_tag(content=axe)
            for v in await pg.evaluate(RUN):
                problems.append(f"{u} {v['impact']} {v['id']} ×{v['n']} {v['sample']}")
        mob = await b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
        pg = await mob.new_page()
        for u in PAGES:
            await pg.goto(WEB + u, wait_until="networkidle"); await pg.wait_for_timeout(1500)
            # 모바일 에뮬레이션에서는 내용이 넓으면 브라우저가 화면을 축소해 innerWidth 도 함께 커짐 → 넘침이 0 으로 보였음.
            # 실제 화면 폭(375)과 비교
            over = await pg.evaluate("Math.max(document.documentElement.scrollWidth, window.innerWidth) - 375")
            if over > 0:
                problems.append(f"{u} 모바일 375px 가로 넘침 {over}px")
        await b.close()
    report("a11y", problems, f"{len(PAGES)}개 화면 axe 위반 0 · 모바일 넘침 0")


if __name__ == "__main__":
    asyncio.run(main())
