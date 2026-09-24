"""에어코리아 대기질 예보통보(getMinuDustFrcstDspth) — 미세먼지(PM10)·초미세먼지(PM25) 권역 등급을 mart.air_forecast 에.

발표 05·11·17·23시. 한 번 조회하면 그날 발표들(오늘·내일, 17시 이후 모레)이 모두 오므로 예보일마다 가장 최근 발표만 씀.
자정~05시에는 오늘 발표가 아직 없어 어제 날짜로도 조회합니다(호출 4회).
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.weather.client import DataGoStop, call, items_of, make_fetcher, now_kst
from atlas.core.config import get_settings
from atlas.core.db import begin
from atlas.domain.visit import parse_inform_grade

_DT = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(\d{1,2})시")


def parse_announced(s: str | None) -> datetime | None:
    """'2026-09-24 17시 발표' → datetime(2026, 9, 24, 17)"""
    m = _DT.search(s or "")
    return datetime.strptime(f"{m.group(1)} {int(m.group(2)):02d}", "%Y-%m-%d %H") if m else None


def latest_by_day(items: list[dict[str, Any]]) -> dict[tuple[date, str], dict[str, Any]]:
    """예보일·항목마다 가장 최근 발표 한 건 (등급 문자열이 빈 발표는 제외)."""
    best: dict[tuple[date, str], dict[str, Any]] = {}
    for it in items:
        code, grade = it.get("informCode"), it.get("informGrade")
        at = parse_announced(it.get("dataTime"))
        try:
            day = date.fromisoformat(str(it.get("informData", ""))[:10])
        except ValueError:
            continue
        if code not in ("PM10", "PM25") or not at or not parse_inform_grade(grade):
            continue
        cur = best.get((day, code))
        if cur is None or at > cur["announced_at"]:
            best[(day, code)] = {"announced_at": at, "grades": parse_inform_grade(grade),
                                 "overall": (it.get("informOverall") or "").strip() or None}
    return best


def collect_air(now: datetime | None = None) -> uuid.UUID:
    now = now or now_kst()
    run_id = runs.start_run("AIR_FCST", scope=f"date={now:%Y-%m-%d}")
    stats: dict[str, Any] = {"days": [], "rows": 0, "stoppedBy": None}
    t0 = time.monotonic()
    fetcher = make_fetcher(run_id, "AIR_FCST")
    url = f"{get_settings().airkorea_base_url}/getMinuDustFrcstDspth"
    items: list[dict[str, Any]] = []
    failed = 0
    try:
        for d in (now.date() - timedelta(days=1), now.date()):
            for code in ("PM10", "PM25"):
                try:
                    body = call(fetcher, url, {"returnType": "json", "numOfRows": 100, "pageNo": 1,
                                               "searchDate": d.isoformat(), "InformCode": code}, "AIR_FCST")
                except DataGoStop as e:
                    stats["stoppedBy"] = str(e)[:200]
                    break
                if body is None:
                    failed += 1
                else:
                    items += items_of(body)
            if stats["stoppedBy"]:
                break
        best = latest_by_day(items)
        rows = [{"d": day, "code": code, "region": region, "grade": grade, "at": v["announced_at"],
                 "overall": v["overall"], "run": run_id}
                for (day, code), v in best.items() for region, grade in v["grades"].items()]
        if rows:
            with begin() as c:
                c.execute(text("""
                    INSERT INTO mart.air_forecast (inform_date, inform_code, region, grade, announced_at, overall, collect_run_id)
                    VALUES (:d, :code, :region, :grade, :at, :overall, :run)
                    ON CONFLICT (inform_date, inform_code, region) DO UPDATE SET grade = EXCLUDED.grade,
                        announced_at = EXCLUDED.announced_at, overall = EXCLUDED.overall, collect_run_id = EXCLUDED.collect_run_id
                    WHERE mart.air_forecast.announced_at <= EXCLUDED.announced_at"""), rows)
        stats.update({"days": sorted({f"{day}" for day, _ in best}), "rows": len(rows), "failedCalls": failed,
                      "calls": fetcher.calls, "errors": fetcher.errors,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "FAILED" if not rows else ("PARTIAL" if failed or stats["stoppedBy"] else "DONE")
        runs.finish_run(run_id, status, stats,
                        error=None if rows else (stats["stoppedBy"] or "받은 예보가 없습니다"))
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
