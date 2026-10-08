"""What-if 조회·저장 SQL — Connection 을 받아 행을 돌려주는 함수만 (규칙·흐름은 service.py, 요약 규칙은 domain/whatif.py)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row, RowMapping

_KNN_EXCLUDING = """
    SELECT a.adm_cd, k.hist_id, round(CAST(k.d AS numeric), 2) AS dist_m
      FROM mart.admin_area a
      LEFT JOIN LATERAL (
            SELECT t.hist_id, t.d FROM (
                SELECT h.hist_id, ST_Distance(h.geom_5179, a.rep_point_5179) AS d
                  FROM mart.post_facility_hist h
                 WHERE h.fin_available AND NOT h.is_center
                   AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
                   AND NOT (h.hist_id = ANY(CAST(:ids AS bigint[])))
                 ORDER BY h.geom_5179 <-> a.rep_point_5179 LIMIT 2) t   -- 인덱스 KNN 후 동률 정리
             ORDER BY t.d, t.hist_id LIMIT 1) k ON true
     WHERE a.stat_year = :y AND {where}
"""


def nearest_removed(c: Connection, run: dict[str, Any], level: int, ids: list[int]) -> dict[str, Any]:
    """1순위 최근접이 제외 목록에 있는 지역 → 지금 거리."""
    return {r[0]: r[1] for r in c.execute(text("""
        SELECT n.adm_cd, n.dist_m FROM mart.area_nearest n
          JOIN mart.admin_area a ON a.adm_cd = n.adm_cd AND a.stat_year = :y
         WHERE n.calc_run_id = :run AND n.rank = 1 AND n.hist_id = ANY(CAST(:ids AS bigint[])) AND a.level = :lvl"""),
        {"y": run["stat_year"], "run": run["calc_run_id"], "ids": ids, "lvl": level})}


def next_nearest(c: Connection, run_id: Any, cds: list[str], ids: list[int]) -> dict[str, tuple[int | None, Any]]:
    """미리 구해 둔 상위 3곳 중 제외되지 않은 가장 가까운 시설 → (시설, 거리)."""
    return {cd: (hid, dist) for cd, hid, dist in c.execute(text("""
            SELECT DISTINCT ON (adm_cd) adm_cd, hist_id, dist_m FROM mart.area_nearest
             WHERE calc_run_id = :run AND adm_cd = ANY(CAST(:cds AS text[]))
               AND NOT (hist_id = ANY(CAST(:ids AS bigint[])))
             ORDER BY adm_cd, rank"""), {"run": run_id, "cds": cds, "ids": ids})}


def knn_excluding(c: Connection, run: dict[str, Any], ids: list[int], *, cds: list[str] | None = None,
                  level: int | None = None) -> list[Row]:
    """제외 목록을 뺀 최근접 금융 우체국을 공간 인덱스로 새로 찾음 — 지정한 지역(cds) 또는 레벨 전체."""
    p: dict[str, Any] = {"asof": run["facility_as_of"], "ids": ids, "y": run["stat_year"]}
    if cds is not None:
        where, p["cds"] = "a.adm_cd = ANY(CAST(:cds AS text[]))", cds
    else:
        where, p["lvl"] = "a.level = :lvl", level
    return c.execute(text(_KNN_EXCLUDING.format(where=where)), p).all()


def facilities_at(c: Connection, ids: list[int], asof: Any) -> list[RowMapping]:
    return c.execute(text("""
        SELECT hist_id, name, fin_available, ST_Y(geom) AS lat, ST_X(geom) AS lon, addr FROM mart.post_facility_hist
         WHERE hist_id = ANY(CAST(:ids AS bigint[]))
           AND valid_from <= :asof AND (valid_to IS NULL OR valid_to > :asof)"""),
        {"ids": ids, "asof": asof}).mappings().all()


def scenario_id_for(c: Connection, run_id: Any, level: int, ids: list[int]) -> Any:
    return c.execute(text("""SELECT scenario_id FROM mart.whatif_scenario
                             WHERE calc_run_id = :run AND level = :lvl AND removed_hist_ids = CAST(:ids AS bigint[])"""),
                     {"run": run_id, "lvl": level, "ids": ids}).scalar()


def area_inputs(c: Connection, run: dict[str, Any], cds: list[str]) -> tuple[dict, dict, dict[str, float]]:
    """영향 지역의 (전체 인구, 65세 이상 인구, 최근접 은행 지점 거리)."""
    pops = {r[0]: r[1] for r in c.execute(text("""
        SELECT adm_cd, tot_ppltn FROM mart.area_population WHERE stat_year = :y AND adm_cd = ANY(CAST(:cds AS text[]))"""),
        {"y": run["stat_year"], "cds": cds})}
    aged = {r[0]: r[1] for r in c.execute(text("""
        SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop WHERE stat_year = :y AND adm_cd = ANY(CAST(:cds AS text[]))"""),
        {"y": run["stat_year"], "cds": cds})}
    bank = {r[0]: float(r[1]) for r in c.execute(text("""
        SELECT adm_cd, value FROM mart.access_metric WHERE calc_run_id = :run AND metric_code = 'NEAREST_BANK_DIST_M'
           AND adm_cd = ANY(CAST(:cds AS text[]))"""), {"run": run["calc_run_id"], "cds": cds})}
    return pops, aged, bank


def has_oa(c: Connection, run_id: Any) -> bool:
    # 계산 통계(oaCount)로 판단 — 'LIMIT 1' 존재 확인은 일반 계획이 계산 여러 개가 쌓인 표를 순차 탐색해 약 100ms (벤치마크)
    return bool(c.execute(text("SELECT coalesce(CAST(stats->>'oaCount' AS int), 0) > 0 FROM mart.calc_run WHERE calc_run_id = :r"),
                          {"r": run_id}).scalar())


def oa_rows(c: Connection, run: dict[str, Any], ids: list[int]) -> list[Row]:
    """닫은 시설이 최근접이던 집계구 → (인구, 지금 거리, 닫은 뒤 거리, 은행 지점·약국·의원 거리)."""
    return c.execute(text("""
        SELECT n.tot_ppltn, n.dist_m, k.d, n.bank_m, n.pharmacy_m, n.clinic_m
          FROM mart.oa_nearest n
          JOIN mart.oa_area o ON o.oa_cd = n.oa_cd AND o.stat_year = :y
          LEFT JOIN LATERAL (
                SELECT ST_Distance(h.geom_5179, o.rep_point_5179) AS d FROM mart.post_facility_hist h
                 WHERE h.fin_available AND NOT h.is_center
                   AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
                   AND NOT (h.hist_id = ANY(CAST(:ids AS bigint[])))
                 ORDER BY h.geom_5179 <-> o.rep_point_5179 LIMIT 1) k ON true
         WHERE n.calc_run_id = :run AND n.hist_id = ANY(CAST(:ids AS bigint[]))"""),
        {"y": run["stat_year"], "asof": run["facility_as_of"], "ids": ids, "run": run["calc_run_id"]}).all()


def insert_scenario(c: Connection, run_id: Any, level: int, ids: list[int], summary: dict[str, Any]) -> Any:
    """새 시나리오 id. 같은 시나리오가 이미 있으면(동시 요청) None."""
    return c.execute(text("""INSERT INTO mart.whatif_scenario (calc_run_id, level, removed_hist_ids, status, summary)
                             VALUES (:run, :lvl, CAST(:ids AS bigint[]), 'DONE', CAST(:s AS jsonb))
                             ON CONFLICT (calc_run_id, level, removed_hist_ids) DO NOTHING
                             RETURNING scenario_id"""),
                     {"run": run_id, "lvl": level, "ids": ids, "s": json.dumps(summary)}).scalar()


def insert_results(c: Connection, sid: Any, results: list[dict[str, Any]], pops: dict, aged: dict,
                   bank: dict[str, float]) -> None:
    for r in results:
        c.execute(text("""INSERT INTO mart.whatif_result (scenario_id, adm_cd, affected_ppltn, affected_aged65,
                                 dist_before_m, dist_after_m, new_nearest_hist_id, nearest_bank_m)
                          VALUES (:sid, :cd, :p, :g, :b, :a, :h, :bk)"""),
                  {"sid": sid, "cd": r["adm_cd"], "p": pops.get(r["adm_cd"]), "g": aged.get(r["adm_cd"]),
                   "b": r["dist_before_m"], "a": r["dist_after_m"], "h": r["new_hist_id"],
                   "bk": bank.get(r["adm_cd"])})


def scenario(c: Connection, sid: Any) -> RowMapping | None:
    return c.execute(text("""SELECT s.*, r.stat_year, r.facility_as_of FROM mart.whatif_scenario s
                             JOIN mart.calc_run r ON r.calc_run_id = s.calc_run_id WHERE s.scenario_id = :id"""),
                     {"id": sid}).mappings().first()


def scenario_areas(c: Connection, sid: Any, stat_year: int) -> list[RowMapping]:
    return c.execute(text("""
        SELECT w.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm, w.affected_ppltn, w.affected_aged65,
               w.dist_before_m, w.dist_after_m, w.nearest_bank_m,
               w.new_nearest_hist_id, h.name AS new_nearest_name, ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon
          FROM mart.whatif_result w
          JOIN mart.admin_area a ON a.adm_cd = w.adm_cd AND a.stat_year = :y
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
          LEFT JOIN mart.post_facility_hist h ON h.hist_id = w.new_nearest_hist_id
         WHERE w.scenario_id = :id
         ORDER BY (w.dist_after_m - w.dist_before_m) DESC NULLS FIRST"""),
        {"id": sid, "y": stat_year}).mappings().all()


def removed_facilities(c: Connection, ids: list[int]) -> list[RowMapping]:
    return c.execute(text("""SELECT hist_id, name, addr, ST_Y(geom) AS lat, ST_X(geom) AS lon
                             FROM mart.post_facility_hist WHERE hist_id = ANY(CAST(:ids AS bigint[]))
                             ORDER BY hist_id"""), {"ids": ids}).mappings().all()


def scenario_exists(c: Connection, sid: Any) -> bool:
    return c.execute(text("SELECT 1 FROM mart.whatif_scenario WHERE scenario_id = :id"), {"id": sid}).first() is not None


def scenario_geojson(c: Connection, sid: Any) -> Any:
    """영향 지역 FeatureCollection (드라이버에 따라 dict 또는 JSON 문자열)."""
    return c.execute(text("""
        SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                 'type', 'Feature', 'id', a.adm_cd,
                 'properties', json_build_object('admCd', a.adm_cd, 'admNm', a.adm_nm,
                     'distBeforeM', w.dist_before_m, 'distAfterM', w.dist_after_m,
                     'increaseM', w.dist_after_m - w.dist_before_m, 'affectedPpltn', w.affected_ppltn,
                     'affectedAged65', w.affected_aged65),
                 'geometry', CAST(ST_AsGeoJSON(coalesce(a.geom_simple, a.geom), 5) AS json))), CAST('[]' AS json)))
          FROM mart.whatif_result w
          JOIN mart.whatif_scenario s ON s.scenario_id = w.scenario_id
          JOIN mart.calc_run r ON r.calc_run_id = s.calc_run_id
          JOIN mart.admin_area a ON a.adm_cd = w.adm_cd AND a.stat_year = r.stat_year
         WHERE w.scenario_id = :id"""), {"id": sid}).scalar_one()
