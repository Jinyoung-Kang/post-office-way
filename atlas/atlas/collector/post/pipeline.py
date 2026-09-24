"""전국 우체국 시설 수집 (FR-101~107).

지역코드 seed 를 순회하며 totalPage 까지 페이지네이션 → raw 저장 → stg 정규화 → DQ → SCD2 병합.
실패한 지역코드는 재시도 후 목록으로 남기고 계속 진행합니다(PARTIAL). --resume 으로 이어서 수집.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.dq.rules import COLLECT_POST_RULES, DQRecorder
from atlas.collector.http import Fetcher
from atlas.collector.post.parser import normalize_item, parse_post_xml
from atlas.collector.post.seed import AreaCode, load_area_codes
from atlas.core.config import get_settings
from atlas.core.db import begin, run_sql_file

log = logging.getLogger(__name__)
PAGE_SIZE = 50  # 명세 최대값
KIND = "POST_AREA"

_STG_COLS = ("post_id", "post_div", "name", "addr", "tel", "lat", "lon", "post_time", "finance_time",
             "lunch_yn", "lunch_time", "post365_yn", "area_code", "mod_dt", "is_center",
             "fin_available", "row_hash")
_INSERT_STG = text(
    f"INSERT INTO stg.post_facility (collect_run_id, {', '.join(_STG_COLS)}) "
    f"VALUES (:run, {', '.join(':' + c for c in _STG_COLS)}) ON CONFLICT DO NOTHING")


def area_url() -> str:
    return f"{get_settings().post_base_url}/searchPostAreaList.do"


def fetch_area(fetcher: Fetcher, code: str, page: int, page_size: int = PAGE_SIZE,
               sleep: Callable[[float], None] = time.sleep):
    s = get_settings()
    res = fetcher.get(area_url(), {"serviceKey": s.post_service_key, "postOffiId": code,
                                   "nowPage": page, "pageCount": page_size}, sleep=sleep)
    parsed = parse_post_xml(res.body) if res.ok else None
    return res, parsed


def collect_post(scope: list[str] | None = None, resume: uuid.UUID | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> uuid.UUID:
    s = get_settings()
    if not s.post_service_key:
        raise RuntimeError("POST_SERVICE_KEY 가 비어 있습니다 (.env 확인).")

    codes: list[AreaCode] = load_area_codes()
    if not codes:
        raise RuntimeError("seed/area_codes.csv 가 비어 있습니다. 먼저 `make discover` 로 지역코드를 만드세요.")
    if scope:
        wanted = set(scope)
        codes = [c for c in codes if c.code in wanted] + \
                [AreaCode(code=c) for c in scope if c not in {x.code for x in codes}]

    if resume:
        prev = runs.reopen_run(resume)
        run_id, stats = resume, prev["stats"]
    else:
        run_id = runs.start_run(KIND, scope=",".join(scope) if scope else "all")
        stats = {}
    stats = {"calls": 0, "pages": 0, "rows": 0, "failedCodes": [], "doneCodes": [], **stats}
    done = set(stats["doneCodes"])
    stats["failedCodes"] = [c for c in stats["failedCodes"] if c not in done]
    fetcher = Fetcher(run_id, "POST_AREA", secrets=[s.post_service_key])
    dq = DQRecorder(collect_run_id=run_id)
    started = time.monotonic()
    delay = s.post_call_delay_ms / 1000
    calls_before = stats["calls"]

    log.info("post collect start", extra={"runId": str(run_id), "codes": len(codes), "resume": bool(resume)})
    try:
        for i, ac in enumerate(codes):
            if ac.code in done:
                continue
            ok, loaded, total_count, page, total_page = True, 0, None, 1, 1
            if resume:  # 이전 시도에서 중간까지 들어간 행을 지워 중복 경보를 막음
                with begin() as c:
                    c.execute(text("DELETE FROM stg.post_facility WHERE collect_run_id = :r AND area_code = :a"),
                              {"r": run_id, "a": ac.code})
            while page <= total_page:
                res, parsed = fetch_area(fetcher, ac.code, page, sleep=sleep)
                stats["pages"] += 1
                if not res.ok or parsed is None or parsed.error:
                    ok = False
                    with begin() as c:
                        dq.add(c, "FETCH_FAILED", "raw.api_response", str(res.response_id),
                               {"areaCode": ac.code, "page": page, "status": res.status,
                                "error": res.error or (parsed.error if parsed else None)})
                    break
                total_page = max(parsed.total_page or 1, 1)
                total_count = parsed.total_count
                rows = [normalize_item(it, ac.code) for it in parsed.items]
                if ac.is_center:
                    for r in rows:
                        r["is_center"], r["fin_available"] = True, False
                with begin() as c:
                    for r in rows:
                        ins = c.execute(_INSERT_STG, {"run": run_id, **r})
                        if ins.rowcount == 0:
                            dq.add(c, "DUP_POST_ID", "stg.post_facility", r["post_id"],
                                   {"areaCode": ac.code, "name": r["name"]})
                        else:
                            loaded += 1
                page += 1
                sleep(delay)
            if ok:
                stats["doneCodes"].append(ac.code)
                if ac.code in stats["failedCodes"]:  # 재개로 성공하면 실패 목록에서 뺌
                    stats["failedCodes"].remove(ac.code)
                stats["rows"] += loaded
                if total_count is not None and total_count != loaded:
                    with begin() as c:
                        dq.add(c, "TOTALCOUNT_MISMATCH", "stg.post_facility", ac.code,
                               {"areaCode": ac.code, "totalCount": total_count, "loaded": loaded})
            elif ac.code not in stats["failedCodes"]:
                stats["failedCodes"].append(ac.code)
            stats["calls"] = calls_before + fetcher.calls
            if i % 10 == 0:
                runs.save_stats(run_id, stats)

        # 좌표 없는 시설은 주소로 채움(카카오 키가 있을 때) → 전체 run 기준 품질 검사 + SCD2 병합
        with begin() as c:
            from atlas.collector.kakao.geocheck import fill_missing_coords

            stats["geocoded"] = fill_missing_coords(c, run_id)
            _run_post_dq(c, dq, run_id)
            counts = dq.record_checks(c, COLLECT_POST_RULES)
            merge = _merge_hist(c, run_id, stats["doneCodes"])
        stats.update({"calls": calls_before + fetcher.calls, "errors": fetcher.errors,
                      "elapsedMs": int((time.monotonic() - started) * 1000) + stats.get("elapsedMs", 0),
                      "dq": counts, "merge": merge})
        status = "DONE" if not stats["failedCodes"] else ("PARTIAL" if stats["doneCodes"] else "FAILED")
        runs.finish_run(run_id, status, stats)
        log.info("post collect finished", extra={"runId": str(run_id), "status": status,
                                                 "rows": stats["rows"], "failed": len(stats["failedCodes"])})
    except Exception as e:
        stats["calls"] = calls_before + fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id


def _run_post_dq(c, dq: DQRecorder, run_id: uuid.UUID) -> None:
    p = {"run": run_id}
    # 전체 run 대상 규칙은 마감 때마다 새로 계산 (재개 시 중복 방지)
    c.execute(text("""DELETE FROM ops.dq_issue WHERE collect_run_id = :run
                      AND check_code IN ('COORD_NULL', 'COORD_GEOCODED', 'COORD_OUT_OF_KR', 'TIME_FORMAT', 'STALE_MOD_DT')"""), p)
    dq.add_sql(c, "COORD_GEOCODED", "stg.post_facility", """
        SELECT post_id, jsonb_build_object('name', name, 'addr', addr, 'lat', lat, 'lon', lon)
        FROM stg.post_facility WHERE collect_run_id = :run AND coord_source = 'GEOCODE'""", p)
    dq.add_sql(c, "COORD_NULL", "stg.post_facility", """
        SELECT post_id AS target_key, jsonb_build_object('name', name, 'areaCode', area_code) AS detail
        FROM stg.post_facility WHERE collect_run_id = :run AND (lat IS NULL OR lon IS NULL)""", p)
    dq.add_sql(c, "COORD_OUT_OF_KR", "stg.post_facility", """
        SELECT post_id, jsonb_build_object('name', name, 'lat', lat, 'lon', lon)
        FROM stg.post_facility WHERE collect_run_id = :run AND lat IS NOT NULL AND lon IS NOT NULL
          AND NOT (lat BETWEEN 33 AND 39 AND lon BETWEEN 124 AND 132)""", p)
    # 시간 형식: 우체국(0·1)의 운영·금융 시간, 점심 운영 시 점심 시간
    dq.add_sql(c, "TIME_FORMAT", "stg.post_facility", r"""
        SELECT post_id, jsonb_build_object('field', f.field, 'value', f.val, 'name', s.name)
        FROM stg.post_facility s
        CROSS JOIN LATERAL (VALUES ('postTime', s.post_time), ('postFinanceTime', s.finance_time),
                                   ('lunchTime', CASE WHEN s.lunch_yn = 'Y' THEN s.lunch_time END)) f(field, val)
        WHERE s.collect_run_id = :run AND s.post_div IN (0, 1) AND f.val IS NOT NULL
          AND f.val !~ '^\s*\d{1,2}\s*:?\s*\d{2}\s*[~\-–〜]\s*\d{1,2}\s*:?\s*\d{2}\s*$'""", p)
    dq.add_sql(c, "STALE_MOD_DT", "stg.post_facility", """
        SELECT post_id, jsonb_build_object('modDt', mod_dt, 'name', name)
        FROM stg.post_facility WHERE collect_run_id = :run AND mod_dt < (current_date - interval '3 years')""", p)


def _merge_hist(c, run_id: uuid.UUID, done_codes: list[str]) -> dict[str, Any]:
    before = c.execute(text("SELECT count(*) FROM mart.post_facility_hist WHERE is_current")).scalar_one()
    run_sql_file(c, "mart_post_hist.sql", {"run": run_id, "done_codes": done_codes})
    after = c.execute(text("SELECT count(*) FROM mart.post_facility_hist WHERE is_current")).scalar_one()
    new_rows = c.execute(text("SELECT count(*) FROM mart.post_facility_hist WHERE collect_run_id = :run"),
                         {"run": run_id}).scalar_one()
    return {"currentBefore": before, "currentAfter": after, "newHistRows": new_rows}
