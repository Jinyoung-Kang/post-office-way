"""② 도로 거리 — 카카오모빌리티 자동차 길찾기로 (지역 대표점 → 직선 최근접 금융 우체국 상위 2곳) 경로 거리·시간.

(지역, 시설) 쌍을 mart.area_road 에 캐시하고 없는 쌍만 호출합니다. 한 번에 ROAD_MAX_CALLS 까지만 부르고
멈추므로(쿼터 보호) 여러 번 실행하면 이어서 채워집니다. 읍면동 → 시군구 순서.
다중 목적지 API 는 반경 10km 제한이 있어 농산어촌에서 쓸 수 없어 단건 API 를 씁니다.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.kakao.client import KakaoStop, call, make_fetcher
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)

# 현재 유효한 금융 가능 우체국 중 직선 상위 N곳 — 아직 캐시에 없는 쌍만
_TODO = text("""
    SELECT a.adm_cd, a.level, ST_X(a.rep_point) AS ox, ST_Y(a.rep_point) AS oy, k.hist_id, k.dx, k.dy
      FROM mart.admin_area a
     CROSS JOIN LATERAL (
            SELECT h.hist_id, ST_X(h.geom) AS dx, ST_Y(h.geom) AS dy
              FROM mart.post_facility_hist h
             WHERE h.is_current AND h.fin_available AND NOT h.is_center
             ORDER BY h.geom_5179 <-> a.rep_point_5179 LIMIT :top) k
     WHERE a.stat_year = :y
       AND NOT EXISTS (SELECT 1 FROM mart.area_road r
                        WHERE r.adm_cd = a.adm_cd AND r.stat_year = a.stat_year AND r.hist_id = k.hist_id
                          AND r.status IN ('OK', 'NO_ROUTE'))
     ORDER BY a.level DESC, a.adm_cd
     LIMIT :lim""")

_UPSERT = text("""
    INSERT INTO mart.area_road (adm_cd, stat_year, hist_id, road_m, drive_s, status, detail, origin)
    VALUES (:cd, :y, :h, :m, :s, :st, :d, :o)
    ON CONFLICT (adm_cd, stat_year, hist_id) DO UPDATE SET road_m = EXCLUDED.road_m, drive_s = EXCLUDED.drive_s,
        status = EXCLUDED.status, detail = EXCLUDED.detail, origin = EXCLUDED.origin, checked_at = now()""")

# 보정 대상: 대표점 출발이 실패했거나(주변 도로 없음 등) 직선의 DETOUR_RATIO 배를 넘는 경로
#  → 그 지역에서 인구가 가장 많은 집계구 대표점(사람이 사는 곳)에서 다시 구함
DETOUR_RATIO = 4
_REPAIR = text("""
    SELECT r.adm_cd, ST_X(ST_Transform(o.rep_point_5179, 4326)) AS ox, ST_Y(ST_Transform(o.rep_point_5179, 4326)) AS oy,
           r.hist_id, ST_X(h.geom) AS dx, ST_Y(h.geom) AS dy
      FROM mart.area_road r
      JOIN mart.admin_area a ON a.adm_cd = r.adm_cd AND a.stat_year = r.stat_year
      JOIN mart.post_facility_hist h ON h.hist_id = r.hist_id
     CROSS JOIN LATERAL (SELECT rep_point_5179 FROM mart.oa_area x
                          WHERE x.stat_year = r.stat_year AND x.rep_point_5179 IS NOT NULL
                            AND x.emd_cd LIKE r.adm_cd || '%'
                          ORDER BY x.tot_ppltn DESC NULLS LAST, x.oa_cd LIMIT 1) o
     WHERE r.stat_year = :y AND r.origin = 'REP'
       AND (r.status = 'NO_ROUTE' OR r.road_m > :ratio * ST_Distance(h.geom_5179, a.rep_point_5179))
     ORDER BY a.level DESC, r.adm_cd
     LIMIT :lim""")


def collect_road(year: int | None = None, max_calls: int | None = None, top: int = 2) -> uuid.UUID:
    s = get_settings()
    year = year or s.stat_year
    budget = max_calls or s.road_max_calls
    run_id = runs.start_run("KAKAO_ROAD", scope=f"top={top};budget={budget};year={year}")
    fetcher = make_fetcher(run_id, "KAKAO_NAVI")
    stats: dict[str, Any] = {"ok": 0, "noRoute": 0, "error": 0, "stoppedBy": None}
    t0 = time.monotonic()
    try:
        with begin() as c:
            todo = [(cd, ox, oy, hid, dx, dy, "REP") for cd, _l, ox, oy, hid, dx, dy in
                    c.execute(_TODO, {"y": year, "top": top, "lim": budget}).all()]
            if len(todo) < budget:   # 새 경로를 다 구했으면 남은 예산으로 의심스러운 경로 보정
                todo += [(*r, "OA") for r in c.execute(_REPAIR, {"y": year, "ratio": DETOUR_RATIO,
                                                                 "lim": budget - len(todo)}).all()]
        stats["repairTried"] = sum(1 for t in todo if t[-1] == "OA")
        for i, (cd, ox, oy, hid, dx, dy, origin) in enumerate(todo):
            try:
                data = call(fetcher, f"{s.kakao_navi_base}/v1/directions",
                            {"origin": f"{ox:.6f},{oy:.6f}", "destination": f"{dx:.6f},{dy:.6f}",
                             "priority": "RECOMMEND", "summary": "true"}, "KAKAO_NAVI")
            except KakaoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
            route = ((data or {}).get("routes") or [{}])[0]
            code = route.get("result_code")
            if code == 0:
                sm = route.get("summary") or {}
                row = {"m": sm.get("distance"), "s": sm.get("duration"), "st": "OK", "d": None}
                stats["ok"] += 1
            elif code == 104:   # 출발지와 도착지가 5m 이내
                row = {"m": 0, "s": 0, "st": "OK", "d": route.get("result_msg")}
                stats["ok"] += 1
            elif code is not None:
                row = {"m": None, "s": None, "st": "NO_ROUTE", "d": f"{code} {route.get('result_msg')}"}
                stats["noRoute"] += 1
            else:
                row = {"m": None, "s": None, "st": "ERROR", "d": "응답 없음"}
                stats["error"] += 1
            if origin == "OA" and row["st"] != "OK":
                # 보정도 실패하면 원래 결과는 그대로 두고, 다시 시도하지 않도록 '보정 시도함'(origin=OA)만 표시
                with begin() as c:
                    c.execute(text("""UPDATE mart.area_road SET origin = 'OA', checked_at = now()
                                      WHERE adm_cd = :cd AND stat_year = :y AND hist_id = :h"""), {"cd": cd, "y": year, "h": hid})
                continue
            with begin() as c:
                c.execute(_UPSERT, {"cd": cd, "y": year, "h": hid, "o": origin, **row})
            if i % 500 == 0:
                log.info("road progress", extra={"i": i, "of": len(todo), **{k: stats[k] for k in ("ok", "noRoute")}})
        with begin() as c:
            stats["remaining"] = len(c.execute(_TODO, {"y": year, "top": top, "lim": 100000}).all()) + \
                len(c.execute(_REPAIR, {"y": year, "ratio": DETOUR_RATIO, "lim": 100000}).all())
            stats["cached"] = c.execute(text("SELECT count(*) FROM mart.area_road WHERE stat_year = :y AND status = 'OK'"),
                                        {"y": year}).scalar_one()
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "elapsedMs": int((time.monotonic() - t0) * 1000)})
        runs.finish_run(run_id, "DONE" if not stats["remaining"] and not stats["stoppedBy"] else "PARTIAL", stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
