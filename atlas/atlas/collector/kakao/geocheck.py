"""③ 카카오 주소 검색으로 시설 좌표 검증·보완.

- geocode(): 주소 → 좌표 (mart.geocode_cache 로 같은 주소는 한 번만 호출)
- fill_missing_coords(): 우체국 API 가 좌표를 안 준 시설을 주소로 채움 (coord_source='GEOCODE') — 수집 파이프라인이 호출
- run_geocheck(): 현재 시설(우체국·365코너·무인창구)의 API 좌표와 주소 좌표를 비교해
  1km 넘게 어긋나면 COORD_ADDR_MISMATCH(WARN). 시설 정보(row_hash)가 바뀐 것만 다시 검사
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.collector import runs
from atlas.collector.dq.rules import DQRecorder
from atlas.collector.kakao.client import KakaoStop, call, clean_addr, haversine_m, make_fetcher
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)
MISMATCH_M = 1000
CHECK_DIVS = (0, 1, 3, 4)   # 우체통(2)·우표판매소(5)는 주소가 대략적이라 제외


def geocode(fetcher, addr: str) -> dict[str, Any] | None:
    """주소 → {lat, lon, matched}. 캐시 우선. 못 찾으면 None."""
    q = clean_addr(addr)
    if not q:
        return None
    with begin() as c:
        hit = c.execute(text("SELECT lat, lon, matched_addr, status FROM mart.geocode_cache WHERE addr = :a"),
                        {"a": q}).first()
    if hit:
        return {"lat": hit[0], "lon": hit[1], "matched": hit[2]} if hit[3] == "OK" else None
    s = get_settings()
    url = f"{s.kakao_local_base}/v2/local/search/address.json"
    data = call(fetcher, url, {"query": q, "size": 1}, "KAKAO_LOCAL")
    docs = (data or {}).get("documents") or []
    if data is not None and not docs and len(q.split()) >= 3:
        # 신설·개편된 시도 이름(예: 전남광주통합특별시)을 모르는 경우 → 시도를 빼고 한 번 더
        data = call(fetcher, url, {"query": q.split(maxsplit=1)[1], "size": 1}, "KAKAO_LOCAL") or data
        docs = (data or {}).get("documents") or []
    if data is None:
        status, row = "ERROR", None
    elif docs:
        d = docs[0]
        status, row = "OK", {"lat": float(d["y"]), "lon": float(d["x"]), "matched": d.get("address_name")}
    else:
        status, row = "NOT_FOUND", None
    with begin() as c:
        c.execute(text("""INSERT INTO mart.geocode_cache (addr, lat, lon, matched_addr, status)
                          VALUES (:a, :lat, :lon, :m, :st)
                          ON CONFLICT (addr) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                              matched_addr = EXCLUDED.matched_addr, status = EXCLUDED.status, fetched_at = now()"""),
                  {"a": q, "lat": row and row["lat"], "lon": row and row["lon"], "m": row and row["matched"], "st": status})
    return row


def fill_missing_coords(c: Connection, run_id: uuid.UUID) -> int:
    """stg 에서 좌표가 없는 행을 주소로 채움. 키가 없으면 0 (좌표 없는 행은 기존대로 mart 에서 제외)."""
    if not get_settings().kakao_rest_api_key:
        return 0
    rows = c.execute(text("""SELECT post_id, addr FROM stg.post_facility
                             WHERE collect_run_id = :r AND (lat IS NULL OR lon IS NULL) AND coalesce(addr, '') <> ''"""),
                     {"r": run_id}).all()
    if not rows:
        return 0
    fetcher = make_fetcher(run_id, "KAKAO_LOCAL")
    n = 0
    try:
        for post_id, addr in rows:
            try:
                g = geocode(fetcher, addr)
            except KakaoStop:
                break
            if g:
                c.execute(text("""UPDATE stg.post_facility SET lat = :lat, lon = :lon, coord_source = 'GEOCODE'
                                  WHERE collect_run_id = :r AND post_id = :p"""),
                          {"lat": g["lat"], "lon": g["lon"], "r": run_id, "p": post_id})
                n += 1
    finally:
        fetcher.close()
    return n


def run_geocheck(max_checks: int = 8000) -> uuid.UUID:
    run_id = runs.start_run("KAKAO_GEO", scope=f"divs={CHECK_DIVS};max={max_checks}")
    fetcher = make_fetcher(run_id, "KAKAO_LOCAL")
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"checked": 0, "mismatch": 0, "notFound": 0, "calls": 0, "stoppedBy": None}
    t0 = time.monotonic()
    try:
        with begin() as c:
            todo = c.execute(text("""
                SELECT h.post_id, h.row_hash, h.addr, ST_Y(h.geom), ST_X(h.geom)
                  FROM mart.post_facility_hist h
                  LEFT JOIN mart.facility_geocheck g ON g.post_id = h.post_id AND g.row_hash = h.row_hash
                 WHERE h.is_current AND h.post_div = ANY(CAST(:divs AS smallint[]))
                   AND (g.post_id IS NULL OR g.status = 'NOT_FOUND')   -- 주소 정리 규칙이 나아지면 다시 시도(캐시로 중복 호출 없음)
                 ORDER BY h.post_div, h.post_id LIMIT :n"""), {"divs": list(CHECK_DIVS), "n": max_checks}).all()
        for post_id, rh, addr, lat, lon in todo:
            try:
                g = geocode(fetcher, addr) if addr else None
            except KakaoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
            if not addr:
                status, d, glat, glon = "NO_ADDR", None, None, None
            elif g is None:
                status, d, glat, glon = "NOT_FOUND", None, None, None
                stats["notFound"] += 1
            else:
                d = round(haversine_m(lat, lon, g["lat"], g["lon"]), 1)
                glat, glon = g["lat"], g["lon"]
                status = "MISMATCH" if d > MISMATCH_M else "OK"
                stats["mismatch"] += status == "MISMATCH"
            with begin() as c:
                c.execute(text("""INSERT INTO mart.facility_geocheck (post_id, row_hash, addr_lat, addr_lon, dist_m, status)
                                  VALUES (:p, :h, :la, :lo, :d, :st)
                                  ON CONFLICT (post_id) DO UPDATE SET row_hash = EXCLUDED.row_hash, addr_lat = EXCLUDED.addr_lat,
                                      addr_lon = EXCLUDED.addr_lon, dist_m = EXCLUDED.dist_m, status = EXCLUDED.status,
                                      checked_at = now()"""),
                          {"p": post_id, "h": rh, "la": glat, "lo": glon, "d": d, "st": status})
            stats["checked"] += 1
            if stats["checked"] % 500 == 0:
                log.info("geocheck progress", extra={"checked": stats["checked"], "of": len(todo)})
        with begin() as c:
            # 현재 시설 전체 기준으로 이슈를 다시 기록 (이번에 검사하지 않은 기존 결과 포함)
            dq.add_sql(c, "COORD_ADDR_MISMATCH", "mart.post_facility_hist", """
                SELECT g.post_id, jsonb_build_object('name', h.name, 'distM', g.dist_m, 'addr', h.addr)
                  FROM mart.facility_geocheck g JOIN mart.post_facility_hist h ON h.post_id = g.post_id AND h.is_current
                 WHERE g.status = 'MISMATCH'""")
            dq.add_sql(c, "ADDR_NOT_FOUND", "mart.post_facility_hist", """
                SELECT g.post_id, jsonb_build_object('name', h.name, 'addr', h.addr)
                  FROM mart.facility_geocheck g JOIN mart.post_facility_hist h ON h.post_id = g.post_id AND h.is_current
                 WHERE g.status = 'NOT_FOUND'""")
            stats["dq"] = dq.record_checks(c, ("COORD_ADDR_MISMATCH", "ADDR_NOT_FOUND"))
            stats["remaining"] = c.execute(text("""
                SELECT count(*) FROM mart.post_facility_hist h
                  LEFT JOIN mart.facility_geocheck g ON g.post_id = h.post_id AND g.row_hash = h.row_hash
                 WHERE h.is_current AND h.post_div = ANY(CAST(:divs AS smallint[])) AND g.post_id IS NULL"""),
                {"divs": list(CHECK_DIVS)}).scalar_one()
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "elapsedMs": int((time.monotonic() - t0) * 1000)})
        runs.finish_run(run_id, "PARTIAL" if stats["stoppedBy"] or stats["remaining"] else "DONE", stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
