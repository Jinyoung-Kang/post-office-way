"""국립중앙의료원 약국·병의원 FullData → mart.care_place (호출 약 110회, 1~2분).

- 약국 getParmacyFullDown(약 2.5만 곳), 병의원 getHsptlMdcncFullDown(약 7.9만 곳 중 종합병원·병원·의원·보건소)
- 종류별로 모든 페이지를 받았을 때만, 이번에 안 보인 곳(폐업)을 지웁니다 — 일부만 받으면 기존 자료 유지
- '모두 받았다'는 응답의 전체 건수(totalCount)만큼 실제 항목을 받았을 때만. 빈 응답·건수 누락은 미완료로 보고,
  모두 받았더라도 기존 행의 큰 비율이 한꺼번에 사라지면 응답 이상으로 보고 삭제를 보류 (ADR-023)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import text

from atlas.ops import runs
from atlas.ops.dq import DQRecorder
from atlas.collector.datago.client import DataGoStop, call, items_of, make_fetcher
from atlas.core.config import get_settings
from atlas.core.db import begin
from atlas.domain.care import to_row

log = logging.getLogger(__name__)
PAGE_ROWS = 1000
# 한 번에 지울 수 있는 기존 행의 상한 — 매주 폐업은 많아야 수백 곳(약국 약 2.5만 곳 중)이라 10%·최소 50곳이면 여유가 있음
MAX_REMOVE_RATIO, MIN_REMOVE_GUARD = 0.10, 50
SOURCES = (("PHARMACY", "NMC_PHARMACY", "pharmacy_url", "getParmacyFullDown"),
           ("CLINIC", "NMC_HOSPITAL", "hospital_url", "getHsptlMdcncFullDown"))


def upsert(c, run_id: uuid.UUID, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    c.execute(text("""
        INSERT INTO mart.care_place (hpid, kind, div, div_name, name, addr, hours, open_holiday, open_sunday,
                                     geom, geom_5179, last_seen, collect_run_id)
        SELECT :hpid, :kind, :div, :div_name, :name, :addr, CAST(:hours AS jsonb), :open_holiday, :open_sunday,
               p, ST_Transform(p, 5179), now(), :run
          FROM (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS p) s
        ON CONFLICT (hpid) DO UPDATE SET kind = EXCLUDED.kind, div = EXCLUDED.div, div_name = EXCLUDED.div_name,
            name = EXCLUDED.name, addr = EXCLUDED.addr, hours = EXCLUDED.hours, open_holiday = EXCLUDED.open_holiday,
            open_sunday = EXCLUDED.open_sunday, geom = EXCLUDED.geom, geom_5179 = EXCLUDED.geom_5179,
            last_seen = now(), collect_run_id = EXCLUDED.collect_run_id"""),
        [{**r, "hours": json.dumps(r["hours"]), "run": run_id} for r in rows])


def collect_kind(fetcher, run_id: uuid.UUID, kind: str, source: str, url: str) -> dict[str, Any]:
    st: dict[str, Any] = {"pages": 0, "total": None, "rows": 0, "skipped": 0, "complete": False}
    started = time.time()
    page = 1
    while True:
        body = call(fetcher, url, {"pageNo": page, "numOfRows": PAGE_ROWS, "_type": "json"}, source)
        if body is None:
            st["failedPage"] = page
            return st
        items = items_of(body)
        st["total"] = int(body.get("totalCount") or 0)
        rows = [r for r in (to_row(kind, it) for it in items) if r]
        st["skipped"] += len(items) - len(rows)
        with begin() as c:
            upsert(c, run_id, rows)
        st["rows"] += len(rows)
        st["pages"] = page
        if not items or page * PAGE_ROWS >= st["total"]:
            break
        page += 1
    # 전국 자료라 전체 건수가 0 이거나 받은 항목이 건수에 못 미치면 '모두 받음'이 아님 → 기존 자료 유지
    seen = st["rows"] + st["skipped"]
    if not st["total"] or seen < st["total"]:
        st["incomplete"] = f"받은 항목 {seen} / 전체 건수 {st['total']}"
        return st
    with begin() as c:
        existing = c.execute(text("SELECT count(*) FROM mart.care_place WHERE kind = :k"), {"k": kind}).scalar_one()
        unseen = c.execute(text("SELECT count(*) FROM mart.care_place WHERE kind = :k AND last_seen < to_timestamp(:t)"),
                           {"k": kind, "t": started}).scalar_one()
        if unseen > max(MAX_REMOVE_RATIO * existing, MIN_REMOVE_GUARD):
            st["removeHeld"] = unseen          # 응답 이상 — 지우지 않고 미완료로 (다음 수집에서 다시 판단)
            DQRecorder(collect_run_id=run_id).add(c, "MASS_CHANGE_HELD", "mart.care_place", kind,
                                                  {"unseen": unseen, "existing": existing})
            log.warning("care removal held", extra={"kind": kind, "unseen": unseen, "existing": existing})
            return st
        st["removed"] = c.execute(text("""DELETE FROM mart.care_place WHERE kind = :k AND last_seen < to_timestamp(:t)"""),
                                  {"k": kind, "t": started}).rowcount
    st["complete"] = True
    return st


def collect_care() -> uuid.UUID:
    s = get_settings()
    run_id = runs.start_run("NMC_CARE", scope="pharmacy,clinic")
    stats: dict[str, Any] = {"stoppedBy": None}
    t0 = time.monotonic()
    fetcher = make_fetcher(run_id, "NMC_PHARMACY")
    try:
        for kind, source, attr, op in SOURCES:
            try:
                stats[kind.lower()] = collect_kind(fetcher, run_id, kind, source, f"{getattr(s, attr)}/{op}")
            except DataGoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
        done = [stats.get(k.lower(), {}).get("complete") for k, *_ in SOURCES]
        stats.update({"rows": sum(stats.get(k.lower(), {}).get("rows", 0) for k, *_ in SOURCES),
                      "calls": fetcher.calls, "errors": fetcher.errors,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "DONE" if all(done) else ("PARTIAL" if any(done) or stats["rows"] else "FAILED")
        with begin() as c:
            DQRecorder(collect_run_id=run_id).record_checks(c, ("MASS_CHANGE_HELD",))
        # PARTIAL 도 사유를 남겨 오류 로그에 보이게 (ADR-023 — 사람이 보고 판단). 원문은 넣지 않고 건수만
        reasons = []
        for k, *_ in SOURCES:
            st = stats.get(k.lower(), {})
            if st.get("removeHeld"):
                reasons.append(f"{k.lower()} 삭제 보류(이번에 안 보인 {st['removeHeld']}곳)")
            elif st.get("incomplete"):
                reasons.append(f"{k.lower()} 미완료({st['incomplete']})")
        runs.finish_run(run_id, status, stats,
                        error=None if status == "DONE" else ("; ".join(reasons) or stats["stoppedBy"] or "미완료"))
    except BaseException as e:  # Ctrl-C 에도 기록을 닫음(test_layers)
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
