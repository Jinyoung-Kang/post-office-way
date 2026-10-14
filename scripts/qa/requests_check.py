"""네트워크 점검 — ① 같은 API 를 두 번 부르는 화면 ② 외부 요청이 평문(http)인지 ③ 지도 없는 화면에서 카카오 SDK 를 받는지
④ CSP 위반 ⑤ 지도 화면(/)이 주소 조건을 읽기 전에 기본 조건 GeoJSON 을 받거나, 지역 카드를 두 번 받는지.
주소 조건이 들어간 화면 상태까지 봅니다.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from _common import MAP_PAGES, PAGES, WEB, launch, report

STATES = PAGES + ["/?in=47", "/?metric=FAR2KM_SHARE", "/?adm=47190", "/?adm=47190&metric=FIN_DESERT_PPLTN",
                  "/today?date=2026-01-01", "/hubs?sido=47", "/rankings?level=3",
                  "/rankings?level=3&sido=11", "/plan?scope=47", "/banks?grade=HIGH&sido=37", "/banks?sort=walk",
                  "/report", "/report/31250"]
DEFAULT_METRIC = "ACCESS_GAP_SCORE"


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def expected_geojson(path: str) -> dict[str, str] | None:
    """지도 화면(/) 주소가 받아야 할 단계구분도 조건 하나 (web/lib/mapQuery.ts mapStateOf·geojsonPathOf 와 같은 규칙).
    주소 조건이 없는 '/' 나 다른 화면은 None."""
    if urlparse(path).path != "/":
        return None
    q = _query(path)
    if not any(q.get(k) for k in ("metric", "in", "adm")):
        return None
    metric, adm, within = q.get("metric") or DEFAULT_METRIC, q.get("adm"), q.get("in")
    if adm and len(adm) > 5:
        parent = within if within and len(within) in (2, 5) and adm.startswith(within) else adm[:5]
        return {"level": "3", "metric": metric, "parent": parent}
    if adm:
        return {"level": "2", "metric": metric}
    if within:
        return {"level": "3", "metric": metric, "parent": within}
    return {"level": "2", "metric": metric}


def map_problems(path: str, api: list[str]) -> list[str]:
    """주소 조건이 있는 지도 화면: GeoJSON 은 주소의 조건으로만(기본 지표 전국 GeoJSON 을 먼저 받지 않게),
    선택 지역 카드(/areas/{adm})는 쿼리와 상관없이 한 번만(calcRunId 없이 한 번, 붙여서 또 한 번 받지 않게)."""
    out: list[str] = []
    want = expected_geojson(path)
    if want is None:
        return out
    geo = [u for u in api if urlparse(u).path == "/areas/geojson"]
    for u in geo:
        if _query(u) != want:
            out.append(f"{path} 주소와 다른 조건의 GeoJSON 요청 {u}")
    if not geo:
        out.append(f"{path} GeoJSON 요청 없음 (기대 {want})")
    adm = _query(path).get("adm")
    if adm:
        n = sum(1 for u in api if urlparse(u).path == f"/areas/{adm}")
        if n != 1:
            out.append(f"{path} 지역 카드 /areas/{adm} 요청 {n}번 (기대 1번)")
    return out


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
            problems += map_problems(path, api)
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
