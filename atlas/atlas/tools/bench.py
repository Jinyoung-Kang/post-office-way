"""API 부하 측정 — 같은 도커 네트워크에서 동시 요청을 보내 경로별 p50/p95/p99·처리량을 잽니다 (`make bench`).

- 캐시 적중(두 번째 요청부터)과 조건부 GET(ETag → 304) 효과를 따로 봅니다.
- What-if 는 무작위 시설 조합이라 캐시를 거의 타지 않는 '실제 계산' 경로입니다.
- 끝에 pg_stat_statements 로 누적 시간이 큰 SQL 상위를 보여 줍니다(원인 분석용).
속도 제한은 make bench 가 측정 동안만 끕니다(RATE_LIMIT_ENABLED=false 로 api 재기동).
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
import time
from typing import Any

import httpx
from sqlalchemy import text

from atlas.core.db import get_engine


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def _run(client: httpx.AsyncClient, name: str, make, n: int, conc: int) -> dict[str, Any]:
    lat: list[float] = []
    codes: dict[int, int] = {}
    size = 0
    sem = asyncio.Semaphore(conc)

    async def one(i: int) -> None:
        nonlocal size
        async with sem:
            method, url, kw = make(i)
            t = time.perf_counter()
            r = await client.request(method, url, **kw)
            lat.append((time.perf_counter() - t) * 1000)
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            size = max(size, len(r.content))

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n)))
    wall = time.perf_counter() - t0
    return {"name": name, "n": n, "conc": conc, "p50": round(statistics.median(lat), 1), "p95": round(_pct(lat, 95), 1),
            "p99": round(_pct(lat, 99), 1), "rps": round(n / wall, 1), "codes": codes, "bytes": size}


async def _main(base: str, n: int, conc: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={"Accept-Encoding": "gzip"}) as c:
        geo = "/api/v1/areas/geojson?level=2&metric=ACCESS_GAP_SCORE"
        await c.get(geo)                                    # 캐시 데우기
        etag = (await c.get(geo)).headers.get("etag", "")
        fac = [f["histId"] for f in (await c.get("/api/v1/facilities?finOnly=true&size=200")).json()["items"]]
        rnd = random.Random(7)
        cases = [
            ("health", lambda i: ("GET", "/api/v1/health", {})),
            ("overview (캐시)", lambda i: ("GET", "/api/v1/overview", {})),
            ("geojson 시군구 (캐시)", lambda i: ("GET", geo, {})),
            ("geojson 시군구 (ETag 304)", lambda i: ("GET", geo, {"headers": {"If-None-Match": etag}})),
            ("geojson 읍면동 서울", lambda i: ("GET", "/api/v1/areas/geojson?level=3&metric=NEAREST_FIN_DIST_M&parent=11", {})),
            ("areas 순위", lambda i: ("GET", f"/api/v1/areas?level=2&metric=ACCESS_GAP_SCORE&size=20&page={i % 5 + 1}", {})),
            ("area 상세", lambda i: ("GET", "/api/v1/areas/37020", {})),
            ("visit 조건 (조회 때 판정)", lambda i: ("GET", "/api/v1/visit/conditions", {})),
            ("hubs 순위", lambda i: ("GET", f"/api/v1/hubs/facilities?page={i % 5 + 1}", {})),
            ("whatif (무작위 1~3곳)", lambda i: ("POST", "/api/v1/whatif",
                                                {"json": {"removeHistIds": rnd.sample(fac, rnd.randint(1, 3)), "level": 3}})),
        ]
        out = []
        for name, make in cases:
            nn = max(20, n // 4) if name.startswith("whatif") else n
            out.append(await _run(c, name, make, nn, conc))
        return out


def top_sql(limit: int = 8) -> list[dict[str, Any]]:
    try:
        with get_engine().connect() as c:
            return [dict(r) for r in c.execute(text("""
                SELECT calls, round(total_exec_time) AS total_ms, round(mean_exec_time::numeric, 2) AS mean_ms,
                       left(regexp_replace(query, '\\s+', ' ', 'g'), 110) AS query
                  FROM pg_stat_statements WHERE query NOT ILIKE '%pg_stat_statements%'
                 ORDER BY total_exec_time DESC LIMIT :n"""), {"n": limit}).mappings()]
    except Exception as e:  # 확장이 없으면 건너뜀
        return [{"note": f"pg_stat_statements 없음: {type(e).__name__}"}]


def run(base: str = "http://api:8100", n: int = 200, conc: int = 16, reset_stats: bool = True) -> dict[str, Any]:
    if reset_stats:
        try:
            with get_engine().begin() as c:
                c.execute(text("SELECT pg_stat_statements_reset()"))
        except Exception:
            pass
    rows = asyncio.run(_main(base, n, conc))
    return {"base": base, "requests": n, "concurrency": conc, "results": rows, "topSql": top_sql()}


def print_table(res: dict[str, Any]) -> None:
    print(f"\n동시 {res['concurrency']} · 경로당 {res['requests']}회 · {res['base']}\n")
    print(f"{'경로':<28}{'p50':>8}{'p95':>8}{'p99':>8}{'req/s':>9}  응답")
    for r in res["results"]:
        codes = ",".join(f"{k}×{v}" for k, v in sorted(r["codes"].items()))
        print(f"{r['name']:<28}{r['p50']:>8}{r['p95']:>8}{r['p99']:>8}{r['rps']:>9}  {codes} · {r['bytes']:,}B")
    print("\n누적 시간 상위 SQL (pg_stat_statements)")
    for q in res["topSql"]:
        print(json.dumps(q, ensure_ascii=False, default=str))
