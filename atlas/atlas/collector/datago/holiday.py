"""한국천문연구원 특일 정보(getRestDeInfo) → mart.holiday. 올해·내년을 한 해 한 번씩 조회(호출 2회)."""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.datago.client import DataGoStop, call, items_of, make_fetcher
from atlas.core.clock import now_kst
from atlas.core.config import get_settings
from atlas.core.db import begin


def parse_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for it in items:
        try:
            d = datetime.strptime(str(it.get("locdate")), "%Y%m%d").date()
        except ValueError:
            continue
        out.append({"d": d, "name": str(it.get("dateName") or "").strip() or "공휴일",
                    "h": str(it.get("isHoliday") or "").upper() == "Y"})
    return out


def collect_holidays(years: list[int] | None = None) -> uuid.UUID:
    today = now_kst().date()
    years = years or [today.year, today.year + 1]
    run_id = runs.start_run("KASI_HOLIDAY", scope=",".join(map(str, years)))
    stats: dict[str, Any] = {"years": years, "rows": 0, "stoppedBy": None}
    t0 = time.monotonic()
    fetcher = make_fetcher(run_id, "KASI_HOLIDAY")
    url = f"{get_settings().holiday_url}/getRestDeInfo"
    try:
        got: list[dict[str, Any]] = []
        failed = []
        for y in years:
            try:
                body = call(fetcher, url, {"solYear": y, "_type": "json", "numOfRows": 100}, "KASI_HOLIDAY")
            except DataGoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
            if body is None:
                failed.append(y)
                continue
            rows = parse_items(items_of(body))
            with begin() as c:
                # 그 해 자료를 통째로 바꿈 (대체공휴일·임시공휴일 지정이 나중에 추가됨)
                c.execute(text("DELETE FROM mart.holiday WHERE locdate BETWEEN :a AND :b"),
                          {"a": date(y, 1, 1), "b": date(y, 12, 31)})
                if rows:
                    c.execute(text("""INSERT INTO mart.holiday (locdate, name, is_holiday, collect_run_id)
                                      VALUES (:d, :name, :h, :run) ON CONFLICT (locdate) DO UPDATE
                                      SET name = mart.holiday.name || '·' || EXCLUDED.name"""),
                              [{**r, "run": run_id} for r in rows])
            got += rows
        stats.update({"rows": len(got), "failedYears": failed, "calls": fetcher.calls,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "FAILED" if not got else ("PARTIAL" if failed or stats["stoppedBy"] else "DONE")
        runs.finish_run(run_id, status, stats, error=None if got else (stats["stoppedBy"] or "받은 휴일이 없습니다"))
    except Exception as e:
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
