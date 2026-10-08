"""설명 글 줄바꿈 점검 — 화면에 그려진 글에서 '문장. 다음 문장'이 같은 줄 흐름에 이어 붙은 곳을 찾습니다.

설명은 문장마다 줄을 바꾸는 규칙(<Sents>·Hero)이라, 줄바꿈 없이 마침표 뒤에 다음 문장이 오면 빠뜨린 곳입니다.
서버 데이터(지표 정의·품질 규칙·예보 안내)로 그리는 글도 잡도록 소스가 아니라 화면을 봅니다.
상호작용 상태(What-if·배치 제안 결과, 지역 카드, 은행 지점 상세, 방문 여건 날짜)를 포함해 데스크톱·모바일 두 폭에서 봅니다.

    python scripts/qa/sentences.py
"""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from _common import WEB, launch, report

JS = r"""
() => {
  const DATE = /\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.?/g;                       // 2026. 10. 08. 같은 날짜 표기는 문장 끝이 아님
  const RE = /[가-힣a-zA-Z0-9)\]’”"%]\.[ \t ]+[^\s]/;               // 마침표 + 같은 줄 공백 + 다음 글자
  const ORD = /(^|[\s(])\d{1,3}\.(?=\s)/g;                                 // '1. 광화문우체국' 같은 순번
  const text = (el) => (el.innerText || "").replace(DATE, "D").replace(ORD, "$1N");
  const out = new Set();
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest('code, pre, .font-mono, svg, script, style, .sr-only, [aria-hidden="true"]')) continue;
    if (!el.offsetParent) continue;
    const t = text(el);
    if (!RE.test(t)) continue;
    if ([...el.children].some((c) => RE.test(text(c)))) continue;          // 가장 안쪽 요소만
    const i = t.search(RE);
    out.add(t.slice(Math.max(0, i - 30), i + 30).replace(/\s+/g, " "));
  }
  return [...out];
}
"""


async def main() -> None:
    found: dict[str, set[str]] = {}
    async with async_playwright() as p:
        b = await launch(p)
        for label, vp, mob in (("데스크톱", {"width": 1440, "height": 900}, False), ("모바일", {"width": 375, "height": 812}, True)):
            ctx = await b.new_context(viewport=vp, is_mobile=mob, has_touch=mob)
            pg = await ctx.new_page()
            W = lambda ms=1500: pg.wait_for_timeout(ms)  # noqa: E731

            async def check(where: str) -> None:
                for s in await pg.evaluate(JS):
                    found.setdefault(s, set()).add(f"{label} {where}")

            async def visit(path: str, ms: int = 2000) -> None:
                await pg.goto(WEB + path, wait_until="networkidle"); await W(ms)
                await check(path)

            for path in ("/overview", "/", "/?adm=47190", "/?adm=4719031000", "/hubs", "/banks", "/rankings",
                         "/report", "/report/37520", "/quality", "/about/metrics", "/nope"):
                await visit(path, 2500 if path.startswith("/?") or path in ("/", "/banks") else 1500)

            await visit("/today", 2500)
            tabs = pg.get_by_role("radiogroup", name="날짜").get_by_role("radio")
            for i in range(await tabs.count()):
                await tabs.nth(i).click(); await W()
                await check(f"/today 날짜 {i}")
            if await pg.locator("tr.clickable").count():
                await pg.locator("tr.clickable").first.click(); await W(2500)
                await check("/today 지역")

            await visit("/whatif", 1000)
            for name in ("의성우체국", "안계우체국"):
                await pg.get_by_label("우체국 검색").fill(name); await W(1300)
                await pg.get_by_role("button", name=name).first.click(); await W(500)
            await pg.get_by_role("button", name="계산하기").click(); await W(3500)
            await check("/whatif 결과")

            await visit("/plan", 1500)
            await pg.get_by_role("button", name="제안 받기").click(); await W(5000)
            await check("/plan 닫을 곳")
            await pg.get_by_role("radio", name="열 곳 찾기").click(); await W(300)
            await pg.get_by_role("button", name="제안 받기").click(); await W(5000)
            await check("/plan 열 곳")
            await ctx.close()
        await b.close()

    problems = [f"{s!r} — {', '.join(sorted(w)[:3])}" for s, w in sorted(found.items())]
    report("sentences", problems, "설명 글이 문장마다 줄을 바꿈 (이어 붙은 문장 0곳)")


if __name__ == "__main__":
    asyncio.run(main())
