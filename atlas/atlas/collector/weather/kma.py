"""기상청 단기예보(getVilageFcst) — 시군구 대표점의 5km 격자별 시간 예보를 mart.weather_hourly 에 적재.

- 발표: 02·05·08·11·14·17·20·23시 (API 제공은 발표 10분 뒤). 가장 최근 발표를 받음
- 시군구 약 250곳 → 격자 중복을 빼면 호출 약 240회(일 한도 1만 회 안)
- 응답 대기(호출당 약 1초)가 대부분이라 격자를 DATAGO_CONCURRENCY(기본 4)개씩 동시에 받음 — 순차 약 290초 → 약 80초
- 같은 시각 예보는 더 최근 발표로만 덮어씀 → 오늘 이미 지난 시각은 앞선 발표 값이 남아 하루 전체를 판정
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.collector import runs
from atlas.collector.datago.client import DataGoStop, call, items_of, make_fetcher
from atlas.core.clock import now_kst
from atlas.core.config import get_settings
from atlas.core.db import begin
from atlas.domain.visit import latlon_to_grid, parse_amount, parse_number

log = logging.getLogger(__name__)
BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
PAGE_ROWS = 1000
CATS = {"TMP": "tmp", "POP": "pop", "PTY": "pty", "PCP": "pcp_mm", "SNO": "sno_cm", "WSD": "wsd", "SKY": "sky"}


def latest_base(now: datetime) -> datetime:
    """now(KST) 기준 받을 수 있는 가장 최근 발표 시각 (발표 +10분부터 제공)."""
    t = now - timedelta(minutes=10)
    for h in reversed(BASE_HOURS):
        if t.hour >= h:
            return t.replace(hour=h, minute=0, second=0, microsecond=0)
    return (t - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)


def stat_year(c: Connection) -> int:
    return c.execute(text("""SELECT stat_year FROM mart.calc_run WHERE status = 'DONE'
                             ORDER BY finished_at DESC NULLS LAST LIMIT 1""")).scalar() or get_settings().stat_year


def ensure_grids(c: Connection, year: int) -> list[tuple[int, int]]:
    """시군구 대표점 → 격자. 새 시군구만 계산해 넣고, 중복 없는 격자 목록을 돌려줌."""
    missing = c.execute(text("""
        SELECT a.adm_cd, ST_Y(a.rep_point), ST_X(a.rep_point) FROM mart.admin_area a
          LEFT JOIN mart.area_grid g ON g.adm_cd = a.adm_cd AND g.stat_year = a.stat_year
         WHERE a.stat_year = :y AND a.level = 2 AND g.adm_cd IS NULL"""), {"y": year}).all()
    if missing:
        c.execute(text("INSERT INTO mart.area_grid (adm_cd, stat_year, nx, ny) VALUES (:cd, :y, :nx, :ny)"),
                  [dict(cd=cd, y=year, **dict(zip(("nx", "ny"), latlon_to_grid(lat, lon), strict=True)))
                   for cd, lat, lon in missing])
    return [tuple(r) for r in c.execute(text(
        "SELECT DISTINCT nx, ny FROM mart.area_grid WHERE stat_year = :y ORDER BY 1, 2"), {"y": year}).all()]


def parse_items(items: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """단기예보 item[] → {예보시각: {tmp, pop, pty, pcp_mm, sno_cm, wsd, sky}}"""
    out: dict[datetime, dict[str, Any]] = {}
    for it in items:
        col = CATS.get(it.get("category", ""))
        if not col:
            continue
        try:
            at = datetime.strptime(f"{it['fcstDate']}{it['fcstTime']}", "%Y%m%d%H%M")
        except (KeyError, ValueError):
            continue
        v = it.get("fcstValue")
        val = parse_amount(v) if col in ("pcp_mm", "sno_cm") else parse_number(v)
        if col in ("pop", "pty", "sky") and val is not None:
            val = int(val)
        out.setdefault(at, {})[col] = val
    return out


def fetch_grid(fetcher, base: datetime, nx: int, ny: int) -> dict[datetime, dict[str, Any]] | None:
    url = f"{get_settings().kma_base_url}/getVilageFcst"
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        body = call(fetcher, url, {"pageNo": page, "numOfRows": PAGE_ROWS, "dataType": "JSON",
                                   "base_date": base.strftime("%Y%m%d"), "base_time": base.strftime("%H%M"),
                                   "nx": nx, "ny": ny}, "KMA_VILAGE")
        if body is None:
            return None
        items += items_of(body)
        if page * PAGE_ROWS >= int(body.get("totalCount") or 0):
            return parse_items(items)
        page += 1


def upsert_hours(c: Connection, run_id: uuid.UUID, base: datetime, nx: int, ny: int,
                 hours: dict[datetime, dict[str, Any]]) -> int:
    rows = [{"nx": nx, "ny": ny, "at": at, "base": base, "run": run_id, **{k: v.get(k) for k in CATS.values()}}
            for at, v in sorted(hours.items())]
    if rows:
        c.execute(text("""
            INSERT INTO mart.weather_hourly (nx, ny, fcst_at, base_at, tmp, pop, pty, pcp_mm, sno_cm, wsd, sky, collect_run_id)
            VALUES (:nx, :ny, :at, :base, :tmp, :pop, :pty, :pcp_mm, :sno_cm, :wsd, :sky, :run)
            ON CONFLICT (nx, ny, fcst_at) DO UPDATE SET base_at = EXCLUDED.base_at, tmp = EXCLUDED.tmp, pop = EXCLUDED.pop,
                pty = EXCLUDED.pty, pcp_mm = EXCLUDED.pcp_mm, sno_cm = EXCLUDED.sno_cm, wsd = EXCLUDED.wsd,
                sky = EXCLUDED.sky, collect_run_id = EXCLUDED.collect_run_id
            WHERE mart.weather_hourly.base_at <= EXCLUDED.base_at"""), rows)
    return len(rows)


def collect_kma(now: datetime | None = None) -> uuid.UUID:
    base = latest_base(now or now_kst())
    run_id = runs.start_run("KMA_FCST", scope=f"base={base:%Y%m%d%H%M}")
    stats: dict[str, Any] = {"base": f"{base:%Y-%m-%d %H:%M}", "grids": 0, "done": 0, "rows": 0,
                             "failedGrids": [], "stoppedBy": None}
    t0 = time.monotonic()
    fetcher = make_fetcher(run_id, "KMA_VILAGE")
    try:
        with begin() as c:
            grids = ensure_grids(c, stat_year(c))
            # 2주 넘은 시간 예보는 판정에 쓰지 않으므로 정리
            c.execute(text("DELETE FROM mart.weather_hourly WHERE fcst_at < CAST(:t AS timestamp) - interval '14 days'"),
                      {"t": base})
        stats["grids"] = len(grids)
        if not grids:
            raise RuntimeError("시군구 경계가 없습니다. 먼저 `make sgis` 를 실행하세요.")
        with ThreadPoolExecutor(max_workers=max(1, get_settings().datago_concurrency), thread_name_prefix="kma") as pool:
            futs = {pool.submit(fetch_grid, fetcher, base, nx, ny): (nx, ny) for nx, ny in grids}
            pending = set(futs)
            while pending:
                done, pending = wait(pending, return_when=FIRST_EXCEPTION)
                for f in done:
                    nx, ny = futs[f]
                    try:
                        hours = f.result()
                    except DataGoStop as e:          # 키·한도 오류 — 남은 격자는 취소
                        stats["stoppedBy"] = str(e)[:200]
                        for p in pending:
                            p.cancel()
                        pending = set()
                        break
                    if hours is None:
                        stats["failedGrids"].append(f"{nx},{ny}")
                        continue
                    with begin() as c:               # 적재는 이 스레드에서 차례로 (DB 쓰기 경합 없음)
                        stats["rows"] += upsert_hours(c, run_id, base, nx, ny, hours)
                    stats["done"] += 1
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "DONE" if stats["done"] == stats["grids"] else ("PARTIAL" if stats["done"] else "FAILED")
        runs.finish_run(run_id, status, stats, error=stats["stoppedBy"] if status == "FAILED" else None)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
