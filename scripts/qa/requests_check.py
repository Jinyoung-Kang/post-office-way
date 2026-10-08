"""네트워크 점검 — ① 같은 API 를 두 번 부르는 화면 ② 외부 요청이 평문(http)인지 ③ 지도 없는 화면에서 카카오 SDK 를 받는지
④ CSP 위반. 주소 조건이 들어간 화면 상태까지 봅니다.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from _common import MAP_PAGES, PAGES, WEB, launch, report

STATES = PAGES + ["/?level=3&parent=47", "/?adm=47190", "/today?date=2026-01-01", "/hubs?sido=47", "/rankings?level=3",
                  "/rankings?level=3&sido=11", "/plan?scope=47", "/banks?grade=HIGH&sido=37", "/banks?sort=walk",
                  "/report", "/report/31250"]
CSP_HOOK = """window.__v=[];document.addEventListener('securitypolicyviolation',
  e=>window.__v.push(e.violatedDirective+' '+e.blockedURI+' '+(e.sourceFile||'')))"""


async def main() -> None:
    problems: list[str] = []
    counts: dict[str, int] = {}
    web_host = urlparse(WEB).netloc
    async with async_playwright() as p:
        b = await launch(p)
        for path in STATES:
            pg = await b.new_page(viewport={"width": 1440, "height": 900})
            await pg.add_init_script(CSP_HOOK)
            reqs: list[str] = []
            pg.on("request", lambda r: reqs.append(r.url))
            await pg.goto(WEB + path, wait_until="networkidle"); await pg.wait_for_timeout(3000)
            api = [u.split("/api/v1", 1)[1] for u in reqs if urlparse(u).netloc == web_host and "/api/v1/" in u]
            counts[path] = len(api)
            for u, n in Counter(api).items():
                if n > 1:
                    problems.append(f"{path} 중복 요청 {u} ×{n}")
            ext = [u for u in reqs if urlparse(u).netloc != web_host and not u.startswith(("data:", "blob:"))]
            for u in ext:
                if u.startswith("http://"):
                    problems.append(f"{path} 평문 외부 요청 {u[:100]}")
            base = path.split("?")[0]
            if base not in MAP_PAGES and any("kakao" in u or "daumcdn" in u for u in ext):
                problems.append(f"{path} 지도 없는 화면에서 카카오 SDK 요청")
            for v in await pg.evaluate("window.__v"):
                if "kakao.js" in v and "eval" in v:      # 카카오 SDK 의 eval 시도는 일부러 막아 둠 (ADR-013)
                    continue
                problems.append(f"{path} CSP 위반 {v[:120]}")
            await pg.close()
        await b.close()
    report("requests", problems, f"{len(STATES)}개 화면 상태 · API 요청 수 {counts}")


if __name__ == "__main__":
    asyncio.run(main())
