"""지역 조회 SQL — 단계구분도·순위 목록·지역 상세·시군구 보고서 (흐름·검증·캐시는 service.py·report.py)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, RowMapping

from atlas.features.facilities import FACILITY_COLS

# 지표 값 + 레벨 전체 기준 순위(1 = 값이 가장 큼)·백분위(값 오름차순 0~100)
# 순위·백분위는 계산 때 미리 넣어 둔 열(V14, calc/10_ranks.sql)을 읽기만 함
_RANKED = """
    SELECT adm_cd, value, rnk, pct, n
      FROM mart.access_metric
     WHERE calc_run_id = :run AND metric_code = :metric AND level = :level AND value IS NOT NULL
"""
_IN_PARENT = """a.stat_year = :year AND a.level = :level
               AND (CAST(:parent AS text) IS NULL OR a.adm_cd LIKE CAST(:parent AS text) || '%')"""


def metric_def(c: Connection, code: str) -> RowMapping | None:
    return c.execute(text("SELECT * FROM mart.metric_def WHERE metric_code = :c"), {"c": code}).mappings().first()


# ------------------------------------------------------------------------------------------------ 단계구분도·목록
def choropleth(c: Connection, run: dict[str, Any], level: int, metric: str, parent: str | None, unit: str | None,
               geom_expr: str, tol: float | None) -> Any:
    """FeatureCollection 을 DB 에서 text 로 — json 으로 받으면 드라이버가 수 MB 를 dict 로 파싱했다가 다시 직렬화함.
    geom_expr 은 service 가 고르는 고정 문자열(사용자 입력 아님)."""
    return c.execute(text(f"""
        WITH m AS ({_RANKED})
        SELECT CAST(json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                 'type', 'Feature', 'id', a.adm_cd,
                 'properties', json_build_object('admCd', a.adm_cd, 'admNm', a.adm_nm, 'level', a.level,
                     'parentCd', a.parent_cd, 'value', m.value, 'unit', CAST(:unit AS text), 'rank', m.rnk, 'rankOf', m.n,
                     'percentile', m.pct, 'totPpltn', p.tot_ppltn, 'agedChildIdx', p.aged_child_idx,
                     'lat', round(CAST(ST_Y(a.rep_point) AS numeric), 5), 'lon', round(CAST(ST_X(a.rep_point) AS numeric), 5)),
                 'geometry', CAST(ST_AsGeoJSON({geom_expr}, 5) AS json)) ORDER BY a.adm_cd), CAST('[]' AS json))) AS text)
          FROM mart.admin_area a
          LEFT JOIN m ON m.adm_cd = a.adm_cd
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
         WHERE {_IN_PARENT}
    """), {"run": run["calc_run_id"], "metric": metric, "level": level, "year": run["stat_year"],
           "parent": parent, "unit": unit, "tol": tol}).scalar_one()


def ranked_page(c: Connection, run: dict[str, Any], level: int, metric: str, parent: str | None, sort: str,
                limit: int, offset: int) -> tuple[int, list[RowMapping]]:
    """(범위 안 지역 수, 지표 순 한 페이지). sort 는 service 가 검증한 'asc'|'desc'."""
    assert sort in ("asc", "desc")
    p = {"run": run["calc_run_id"], "metric": metric, "level": level, "year": run["stat_year"],
         "parent": parent, "lim": limit, "off": offset}
    total = c.execute(text(f"SELECT count(*) FROM mart.admin_area a WHERE {_IN_PARENT}"), p).scalar_one()
    rows = c.execute(text(f"""
        WITH m AS ({_RANKED})
        SELECT a.adm_cd, a.adm_nm, a.parent_cd, pa.adm_nm AS parent_nm, m.value, m.rnk, m.n, m.pct,
               p.tot_ppltn, p.aged_child_idx, ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon
          FROM mart.admin_area a
          LEFT JOIN m ON m.adm_cd = a.adm_cd
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE {_IN_PARENT}
         ORDER BY m.value {sort} NULLS LAST, a.adm_cd
         LIMIT :lim OFFSET :off"""), p).mappings().all()
    return total, rows


# ------------------------------------------------------------------------------------------------ 지역 상세
def area(c: Connection, adm_cd: str, y: int) -> RowMapping | None:
    return c.execute(text("""
        SELECT a.adm_cd, a.adm_nm, a.level, a.parent_cd, pa.adm_nm AS parent_nm, a.src_crs,
               ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon,
               ST_XMin(a.geom) AS minx, ST_YMin(a.geom) AS miny, ST_XMax(a.geom) AS maxx, ST_YMax(a.geom) AS maxy,
               round(CAST(ST_Area(a.geom_5179) / 1e6 AS numeric), 2) AS area_km2,
               p.tot_ppltn, p.ppltn_dnsty, p.aged_child_idx, p.avg_age, p.loaded_at AS pop_loaded_at
          FROM mart.admin_area a
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE a.adm_cd = :cd AND a.stat_year = :y"""), {"cd": adm_cd, "y": y}).mappings().first()


def area_metrics(c: Connection, run_id: Any, adm_cd: str) -> list[RowMapping]:
    return c.execute(text("""
        SELECT d.metric_code, d.name_ko, d.unit, d.higher_is_worse, m.value, m.rnk, m.pct, m.n
          FROM mart.access_metric m
          JOIN mart.metric_def d ON d.metric_code = m.metric_code
         WHERE m.calc_run_id = :run AND m.adm_cd = :cd
         ORDER BY d.sort_order, d.metric_code"""), {"run": run_id, "cd": adm_cd}).mappings().all()


def nearest_facilities(c: Connection, run_id: Any, adm_cd: str, y: int) -> list[RowMapping]:
    """최근접 금융 우체국 3곳 + 도로 거리(있으면)."""
    return c.execute(text(f"""
        SELECT n.rank, n.dist_m, r.road_m, r.drive_s, {FACILITY_COLS}
          FROM mart.area_nearest n JOIN mart.post_facility_hist h ON h.hist_id = n.hist_id
          LEFT JOIN mart.area_road r ON r.adm_cd = n.adm_cd AND r.stat_year = :y AND r.hist_id = n.hist_id AND r.status = 'OK'
         WHERE n.calc_run_id = :run AND n.adm_cd = :cd ORDER BY n.rank"""),
        {"run": run_id, "cd": adm_cd, "y": y}).mappings().all()


def nearest_banks(c: Connection, adm_cd: str, y: int) -> list[RowMapping]:
    """대표점에서 가까운 은행 지점 3곳."""
    return c.execute(text("""
        SELECT b.name, b.addr, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
               round(CAST(ST_Distance(b.geom_5179, a.rep_point_5179) AS numeric), 1) AS dist_m
          FROM mart.admin_area a
         CROSS JOIN LATERAL (SELECT * FROM mart.bank_branch_current b
                              ORDER BY b.geom_5179 <-> a.rep_point_5179 LIMIT 3) b
         WHERE a.adm_cd = :cd AND a.stat_year = :y"""), {"cd": adm_cd, "y": y}).mappings().all()


def facility_counts(c: Connection, adm_cd: str, y: int, level: int, asof: Any) -> list[RowMapping]:
    """지역 안 시설 종류별 수 (계산 시점)."""
    return c.execute(text("""
        SELECT h.post_div, count(*) AS n, count(*) FILTER (WHERE h.fin_available) AS fin
          FROM mart.facility_area_map m JOIN mart.post_facility_hist h ON h.hist_id = m.hist_id
         WHERE m.stat_year = :y AND m.level = :lvl AND m.adm_cd = :cd
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
         GROUP BY h.post_div ORDER BY h.post_div"""),
        {"y": y, "lvl": level, "cd": adm_cd, "asof": asof}).mappings().all()


def resident_pop(c: Connection, adm_cd: str, y: int) -> RowMapping | None:
    return c.execute(text("""SELECT ref_period, tot_ppltn, aged65_ppltn, aged65_ratio, match_method, loaded_at
                             FROM mart.area_resident_pop WHERE adm_cd = :cd AND stat_year = :y"""),
                     {"cd": adm_cd, "y": y}).mappings().first()


# ------------------------------------------------------------------------------------------------ 시군구 보고서
def _report_params(run: dict[str, Any], adm_cd: str) -> dict[str, Any]:
    return {"r": run["calc_run_id"], "y": run["stat_year"], "cd": adm_cd, "asof": run["facility_as_of"]}


def report_area(c: Connection, run: dict[str, Any], adm_cd: str) -> RowMapping | None:
    """시군구 개요 — 이름·시도·면적·인구·KOSIS 고령인구(최신 기준 시점)·읍면동 수·경계 상자."""
    return c.execute(text("""
        SELECT a.adm_cd, a.adm_nm, a.parent_cd, pa.adm_nm AS parent_nm,
               round(CAST(ST_Area(a.geom_5179) / 1e6 AS numeric), 1) AS area_km2,
               p.tot_ppltn, rp.aged65_ppltn, rp.aged65_ratio, rp.ref_period,
               (SELECT count(*) FROM mart.admin_area e WHERE e.stat_year = a.stat_year AND e.level = 3 AND e.parent_cd = a.adm_cd) AS emd_n,
               ST_XMin(a.geom) AS minx, ST_YMin(a.geom) AS miny, ST_XMax(a.geom) AS maxx, ST_YMax(a.geom) AS maxy
          FROM mart.admin_area a
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year   -- 시도 이름
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
          LEFT JOIN LATERAL (SELECT aged65_ppltn, aged65_ratio, ref_period FROM mart.area_resident_pop
                              WHERE adm_cd = a.adm_cd AND stat_year = a.stat_year ORDER BY ref_period DESC LIMIT 1) rp ON true
         WHERE a.adm_cd = :cd AND a.stat_year = :y AND a.level = 2"""), _report_params(run, adm_cd)).mappings().first()


def report_metrics(c: Connection, run: dict[str, Any], adm_cd: str, codes: list[str]) -> list[RowMapping]:
    """지표 값 + 전국 시군구 중앙값(비교 기준)."""
    return c.execute(text("""
        SELECT d.metric_code, d.name_ko, d.unit, d.higher_is_worse, m.value, m.rnk, m.n, m.pct,
               (SELECT round(CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY x.value) AS numeric), 2) FROM mart.access_metric x
                 WHERE x.calc_run_id = m.calc_run_id AND x.metric_code = m.metric_code AND x.level = 2) AS median
          FROM mart.access_metric m JOIN mart.metric_def d ON d.metric_code = m.metric_code
         WHERE m.calc_run_id = :r AND m.adm_cd = :cd AND m.metric_code = ANY(:codes)"""),
        {**_report_params(run, adm_cd), "codes": codes}).mappings().all()


def report_posts(c: Connection, run: dict[str, Any], adm_cd: str) -> list[RowMapping]:
    """시군구 안 금융 우체국 — 혼자 맡는 생활 거점 인구가 큰 순."""
    return c.execute(text("""
        SELECT h.hist_id, h.name, h.post_div, h.finance_time, h.post365_yn, ST_Y(h.geom) AS lat, ST_X(h.geom) AS lon,
               fh.served_ppltn, fh.sole_fin_ppltn, fh.sole_hub_ppltn
          FROM mart.facility_area_map fm
          JOIN mart.post_facility_hist h ON h.hist_id = fm.hist_id
          LEFT JOIN mart.facility_hub fh ON fh.calc_run_id = :r AND fh.hist_id = h.hist_id
         WHERE fm.stat_year = :y AND fm.level = 2 AND fm.adm_cd = :cd AND h.fin_available AND NOT h.is_center
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
         ORDER BY coalesce(fh.sole_hub_ppltn, 0) DESC, coalesce(fh.sole_fin_ppltn, 0) DESC, h.name"""),
        _report_params(run, adm_cd)).mappings().all()


def report_facility_counts(c: Connection, run: dict[str, Any], adm_cd: str) -> RowMapping:
    return c.execute(text("""
        SELECT count(*) AS all_n, count(*) FILTER (WHERE h.fin_available AND NOT h.is_center) AS fin_n,
               count(*) FILTER (WHERE h.post365_yn = 'Y') AS c365
          FROM mart.facility_area_map fm JOIN mart.post_facility_hist h ON h.hist_id = fm.hist_id
         WHERE fm.stat_year = :y AND fm.level = 2 AND fm.adm_cd = :cd
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)"""),
        _report_params(run, adm_cd)).mappings().one()


def report_banks(c: Connection, run: dict[str, Any], adm_cd: str) -> list[RowMapping]:
    """시군구 안 은행 지점 폐쇄 영향 — 잃는 인구가 큰 순."""
    return c.execute(text("""
        SELECT b.place_id, bp.name, b.brand, b.grade, b.reasons, b.catch_ppltn, b.lost_ppltn, b.walk_lost_ppltn
          FROM mart.bank_impact b JOIN mart.bank_place bp ON bp.place_id = b.place_id
         WHERE b.calc_run_id = :r AND b.adm_cd = :cd
         ORDER BY b.lost_ppltn DESC, b.catch_ppltn DESC"""), _report_params(run, adm_cd)).mappings().all()


def report_emds(c: Connection, run: dict[str, Any], adm_cd: str, codes: list[str]) -> list[RowMapping]:
    """읍면동 표 + 작은 지도(30~200m 단순화 경계) — 지도 SDK 없이 SVG 로 그려 인쇄에도 그대로."""
    return c.execute(text("""
        SELECT e.adm_cd, e.adm_nm, p.tot_ppltn,
               jsonb_object_agg(m.metric_code, m.value) FILTER (WHERE m.metric_code IS NOT NULL) AS vals,
               CAST(ST_AsGeoJSON(coalesce(e.geom_simple, e.geom), 4) AS json) AS geom
          FROM mart.admin_area e
          LEFT JOIN mart.area_population p ON p.adm_cd = e.adm_cd AND p.stat_year = e.stat_year
          LEFT JOIN mart.access_metric m ON m.calc_run_id = :r AND m.adm_cd = e.adm_cd AND m.metric_code = ANY(:codes)
         WHERE e.stat_year = :y AND e.level = 3 AND e.parent_cd = :cd
         GROUP BY e.adm_cd, e.adm_nm, p.tot_ppltn, e.geom_simple, e.geom
         ORDER BY e.adm_cd"""), {**_report_params(run, adm_cd), "codes": codes}).mappings().all()
