"""계산 실행 (calc_run) — 스냅샷 → 공간 조인 → 최근접 3 → 지표 → 품질 검사 (FR-301~304, FR-601).

모든 단계를 한 트랜잭션에서 실행하므로 중간에 실패하면 지표가 반쯤 남지 않습니다.
화면의 모든 숫자는 calc_run_id 를 가집니다.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text

from atlas.collector.dq.rules import CALC_RULES, DQRecorder
from atlas.core.config import get_settings
from atlas.core.db import get_engine, run_sql_file
from atlas.domain.rules import RULE_VERSION

log = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "radiusKm": [1, 2, 5],
    "weights": {"dist": 0.6, "aged": 0.4},
    "snapM": 2000,          # 폴리곤 밖 시설을 최근접 지역에 붙이는 허용 거리
    "missCheckM": 20000,    # 이 거리 안인데 매핑 안 된 시설만 SPATIAL_JOIN_MISS (범위 밖 시도 제외)
    "farKm": 2,             # AGED65_FAR_PPLTN 의 '먼 거리' 기준
}


class CalcRunInProgress(RuntimeError):
    pass


def running_calc(engine: Engine | None = None) -> str | None:
    with (engine or get_engine()).begin() as c:
        r = c.execute(text("""SELECT calc_run_id FROM mart.calc_run WHERE status = 'RUNNING'
                              AND created_at > now() - interval '2 hours' LIMIT 1""")).first()
    return str(r[0]) if r else None


def create_calc_run(stat_year: int | None = None, levels: list[int] | None = None,
                    params: dict[str, Any] | None = None, facility_as_of: datetime | None = None,
                    engine: Engine | None = None) -> uuid.UUID:
    s = get_settings()
    eng = engine or get_engine()
    if rid := running_calc(eng):
        raise CalcRunInProgress(f"계산이 이미 실행 중입니다 (calcRunId={rid})")
    p = {**DEFAULT_PARAMS, **(params or {})}
    p["levels"] = sorted(levels or p.get("levels") or s.levels)
    p["ruleVersion"] = RULE_VERSION
    with eng.begin() as c:
        return c.execute(text("""INSERT INTO mart.calc_run (stat_year, facility_as_of, params, status)
                                 VALUES (:y, :asof, CAST(:p AS jsonb), 'RUNNING') RETURNING calc_run_id"""),
                         {"y": stat_year or s.stat_year, "asof": facility_as_of or datetime.now(timezone.utc),
                          "p": json.dumps(p)}).scalar_one()


def execute_calc_run(calc_run_id: uuid.UUID, engine: Engine | None = None) -> dict[str, Any]:
    eng = engine or get_engine()
    t0 = time.monotonic()
    with eng.begin() as c:
        row = c.execute(text("SELECT stat_year, facility_as_of, params FROM mart.calc_run WHERE calc_run_id = :id"),
                        {"id": calc_run_id}).one()
    stat_year, as_of, params = row
    levels = [int(x) for x in params["levels"]]
    base = {"calc_run_id": calc_run_id, "stat_year": stat_year, "as_of": as_of, "levels": levels}
    timings: dict[str, int] = {}

    def step(name: str, fn) -> None:
        t = time.monotonic()
        fn()
        timings[name] = int((time.monotonic() - t) * 1000)

    try:
        with eng.begin() as c:
            c.execute(text("SET LOCAL work_mem = '128MB'"))
            step("snapshot", lambda: run_sql_file(c, "calc/00_snapshot.sql", base))
            n_fac, n_fin, n_area = c.execute(text(
                "SELECT (SELECT count(*) FROM calc_fac), (SELECT count(*) FROM calc_fin), (SELECT count(*) FROM calc_area)"
            )).one()
            if n_area == 0:
                raise RuntimeError(f"{stat_year}년 level {levels} 행정구역이 없습니다. 먼저 `make sgis` 를 실행하세요.")
            if n_fin == 0:
                raise RuntimeError("금융 가능 시설이 없습니다. 먼저 `make collect` 를 실행하세요.")
            step("spatialJoin", lambda: run_sql_file(c, "calc/01_facility_area_map.sql",
                                                     {**base, "snap_m": float(params.get("snapM", 2000))}))
            step("nearest", lambda: run_sql_file(c, "calc/02_area_nearest.sql", base))
            step("metrics", lambda: run_sql_file(c, "calc/03_metrics.sql", base))

            def radius() -> None:
                for km in params.get("radiusKm", [1, 2, 5]):
                    code = f"FAC_CNT_R{int(km)}KM"
                    c.execute(text("""INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation,
                                          higher_is_worse, sort_order)
                                      VALUES (:c, :n, '개', :f, '행정구역 경계 밖 시설도 포함. 대표점 기준.', false, 20 + :k)
                                      ON CONFLICT (metric_code) DO NOTHING"""),
                              {"c": code, "n": f"반경 {int(km)}km 안 금융 가능 우체국 수",
                               "f": f"ST_DWithin(대표점, 금융 가능 시설, {int(km) * 1000}m) 개수 (EPSG:5179).",
                               "k": int(km)})
                    run_sql_file(c, "calc/03b_radius.sql", {**base, "metric_code": code, "radius_m": km * 1000.0})

            step("radius", radius)
            w = params.get("weights", {})
            step("gapScore", lambda: run_sql_file(c, "calc/04_gap_score.sql",
                                                  {**base, "w_dist": float(w.get("dist", 0.6)),
                                                   "w_aged": float(w.get("aged", 0.4))}))
            step("kosisAged", lambda: run_sql_file(c, "calc/05_kosis_aged.sql",
                                                   {**base, "far_m": float(params.get("farKm", 2)) * 1000}))
            kosis_period = c.execute(text("""SELECT max(ref_period) FROM mart.area_resident_pop
                                             WHERE stat_year = :y"""), {"y": stat_year}).scalar()
            far = {**base, "far_m": float(params.get("farKm", 2)) * 1000}
            step("oa", lambda: run_sql_file(c, "calc/06_oa.sql", far))          # ① 집계구
            step("bank", lambda: run_sql_file(c, "calc/07_bank.sql", far))      # ④ 금융 공백
            step("road", lambda: run_sql_file(c, "calc/08_road.sql", base))     # ② 도로 거리
            extra = c.execute(text("""SELECT
                (SELECT count(*) FROM mart.oa_nearest WHERE calc_run_id = :id),
                (SELECT count(*) FROM mart.access_metric WHERE calc_run_id = :id AND metric_code = 'NEAREST_BANK_DIST_M'),
                (SELECT count(*) FROM mart.access_metric WHERE calc_run_id = :id AND metric_code = 'NEAREST_FIN_ROAD_M')"""),
                {"id": calc_run_id}).one()
            dq = DQRecorder(calc_run_id=calc_run_id)
            dq.add_sql(c, "SPATIAL_JOIN_MISS", "mart.post_facility_hist", """
                SELECT CAST(f.hist_id AS text) AS target_key,
                       jsonb_build_object('method', coalesce(m.method, 'NONE'), 'postDiv', f.post_div,
                                          'lon', ST_X(f.geom), 'lat', ST_Y(f.geom)) AS detail
                  FROM calc_fac f
                  LEFT JOIN mart.facility_area_map m ON m.hist_id = f.hist_id AND m.stat_year = :y
                                                    AND m.level = CAST(:lvl AS smallint)
                 WHERE coalesce(m.method, 'NONE') <> 'CONTAINS'
                   AND EXISTS (SELECT 1 FROM calc_area a WHERE a.level = CAST(:lvl AS smallint)
                                AND ST_DWithin(a.geom_5179, f.geom_5179, CAST(:miss AS float8)))""",
                       {"y": stat_year, "lvl": min(levels), "miss": float(params.get("missCheckM", 20000))})
            dq.add_sql(c, "GEOM_INVALID", "mart.admin_area", """
                SELECT a.adm_cd, jsonb_build_object('reason', ST_IsValidReason(a.geom))
                  FROM calc_area a WHERE NOT ST_IsValid(a.geom)""")
            dq_counts = dq.record_checks(c, CALC_RULES)
            per_level = {str(r[0]): r[1] for r in c.execute(text(
                "SELECT level, count(*) FROM calc_area GROUP BY level ORDER BY level"))}
            stats = {"facilities": n_fac, "finFacilities": n_fin, "areas": n_area, "areasByLevel": per_level,
                     "kosisRefPeriod": kosis_period,
                     "oaCount": extra[0], "bankAreas": extra[1], "roadAreas": extra[2],
                     "timingsMs": timings, "dq": dq_counts,
                     "elapsedMs": int((time.monotonic() - t0) * 1000)}
            # now() 는 트랜잭션 시작 시각 → 실제 끝난 시각은 clock_timestamp()
            c.execute(text("""UPDATE mart.calc_run SET status = 'DONE', stats = CAST(:s AS jsonb), finished_at = clock_timestamp()
                              WHERE calc_run_id = :id"""), {"s": json.dumps(stats), "id": calc_run_id})
        log.info("calc done", extra={"calcRunId": str(calc_run_id), **{k: v for k, v in stats.items() if k != "dq"}})
        _invalidate_cache()
        return stats
    except Exception as e:
        with eng.begin() as c:
            c.execute(text("""UPDATE mart.calc_run SET status = 'FAILED', error = :e, finished_at = now()
                              WHERE calc_run_id = :id"""), {"e": f"{type(e).__name__}: {e}"[:2000], "id": calc_run_id})
        log.exception("calc failed", extra={"calcRunId": str(calc_run_id)})
        raise


def run_calc(stat_year: int | None = None, levels: list[int] | None = None,
             params: dict[str, Any] | None = None, engine: Engine | None = None) -> uuid.UUID:
    rid = create_calc_run(stat_year, levels, params, engine=engine)
    execute_calc_run(rid, engine=engine)
    return rid


def _invalidate_cache() -> None:
    """새 calc_run 이 '최신'이 되므로 지도 GeoJSON 캐시(geo:*)를 비웁니다."""
    try:
        from atlas.api.cache import delete_prefix

        delete_prefix("geo:")
        delete_prefix("areas:")
    except Exception:  # 캐시는 선택 요소 — 실패해도 계산 결과는 유효
        log.warning("cache invalidation skipped")
