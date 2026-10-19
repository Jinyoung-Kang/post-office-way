"""배치 제안 조회 SQL — 후보 시설, 수요 지점별 가까운 시설 상위 N, 가중치 원자료, 이름 (흐름은 service.py, 알고리즘은 domain/placement.py)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

# 계산 시점에 유효한 금융 가능 우체국 (우편집중국 제외)
_SNAP = "h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof) AND h.fin_available AND NOT h.is_center"


def candidates(c: Connection, run: dict[str, Any], scope: str) -> dict[int, dict[str, Any]]:
    """범위 안 후보 시설 → {hist_id: {hist_id, name, addr, lat, lon}} (시설-지역 매핑은 계산한 가장 큰 레벨 기준)."""
    return {r["hist_id"]: dict(r) for r in c.execute(text(f"""
        SELECT h.hist_id, h.name, h.addr, ST_Y(h.geom) AS lat, ST_X(h.geom) AS lon
          FROM mart.post_facility_hist h
          JOIN mart.facility_area_map m ON m.hist_id = h.hist_id AND m.stat_year = :y AND m.level = :mlvl
         WHERE {_SNAP} AND m.adm_cd LIKE :scope || '%'"""),
        {"asof": run["facility_as_of"], "y": run["stat_year"], "scope": scope,
         "mlvl": min(int(x) for x in run["params"].get("levels", [2]))}).mappings()}


def has_oa_in(c: Connection, y: int, scope: str) -> bool:
    return c.execute(text("""SELECT 1 FROM mart.oa_area WHERE stat_year = :y AND emd_cd LIKE :scope || '%'
                                AND rep_point_5179 IS NOT NULL AND tot_ppltn > 0 LIMIT 1"""),
                     {"y": y, "scope": scope}).first() is not None


def demand_top_n(c: Connection, run: dict[str, Any], level: int, scope: str, ids: list[int], use_oa: bool,
                 top_n: int) -> list[Row]:
    """수요 지점(집계구 또는 지역 대표점)마다 가까운 시설 상위 top_n → (지점, 묶음 지역, 시설, 거리) 거리순.
    범위 안 지점 + 범위 밖이지만 이번 계산에서 1순위가 후보인 지점."""
    if use_oa:
        pts_sql = """SELECT o.oa_cd AS cd, o.emd_cd AS grp, o.rep_point_5179 AS p FROM mart.oa_area o
                      WHERE o.stat_year = :y AND o.rep_point_5179 IS NOT NULL AND o.tot_ppltn > 0
                        AND (o.emd_cd LIKE :scope || '%' OR o.oa_cd IN (
                             SELECT n.oa_cd FROM mart.oa_nearest n WHERE n.calc_run_id = :run
                                AND n.hist_id = ANY(CAST(:ids AS bigint[]))))"""
    else:
        pts_sql = """SELECT a.adm_cd AS cd, a.adm_cd AS grp, a.rep_point_5179 AS p FROM mart.admin_area a
                      WHERE a.stat_year = :y AND a.level = :lvl
                        AND (a.adm_cd LIKE :scope || '%' OR EXISTS (
                             SELECT 1 FROM mart.area_nearest n WHERE n.calc_run_id = :run AND n.adm_cd = a.adm_cd
                                AND n.rank = 1 AND n.hist_id = ANY(CAST(:ids AS bigint[]))))"""
    return c.execute(text(f"""
        WITH pts AS ({pts_sql})
        SELECT pts.cd, pts.grp, k.hist_id, k.d
          FROM pts
         CROSS JOIN LATERAL (
                SELECT h.hist_id, ST_Distance(h.geom_5179, pts.p) AS d
                  FROM mart.post_facility_hist h WHERE {_SNAP}
                 ORDER BY h.geom_5179 <-> pts.p LIMIT {int(top_n)}) k
         ORDER BY pts.cd, k.d, k.hist_id"""),
        {"y": run["stat_year"], "lvl": level, "scope": scope, "run": run["calc_run_id"], "ids": ids,
         "asof": run["facility_as_of"]}).all()


def area_pop(c: Connection, y: int, cds: list[str]) -> dict[str, float]:
    return {r[0]: float(r[1] or 0) for r in c.execute(text("""SELECT adm_cd, tot_ppltn FROM mart.area_population
                                                             WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""),
                                                        {"y": y, "c": cds})}


def area_aged65(c: Connection, y: int, cds: list[str]) -> dict[str, float]:
    return {r[0]: float(r[1] or 0) for r in c.execute(text("""SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop
                                                             WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""),
                                                        {"y": y, "c": cds})}


def oa_pop_aged_ratio(c: Connection, y: int, oas: list[str]) -> list[Row]:
    """집계구 → (집계구, 인구, 상위 읍면동 고령인구 비율 %)."""
    return c.execute(text("""SELECT o.oa_cd, o.tot_ppltn, r.aged65_ratio FROM mart.oa_area o
                              LEFT JOIN mart.area_resident_pop r ON r.adm_cd = o.emd_cd AND r.stat_year = o.stat_year
                             WHERE o.stat_year = :y AND o.oa_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": oas}).all()


def sole_hub(c: Connection, run_id: Any, ids: list[int]) -> dict[int, Any]:
    """⑦ 닫으면 생활 거점을 모두 잃는 인구(우체국별)."""
    return {h: s for h, s in c.execute(text("""SELECT hist_id, sole_hub_ppltn FROM mart.facility_hub
                                               WHERE calc_run_id = :r AND hist_id = ANY(CAST(:ids AS bigint[]))"""),
                                       {"r": run_id, "ids": ids})}


def net_out_of_facilities(c: Connection, run_id: Any, y: int, ids: list[int]) -> dict[int, tuple[Any, Any]]:
    """시설이 있는 시군구의 12개월 순유출(천 명당)·백분위 → {hist_id: (값, 백분위)} — 인구 추세 경고용 (ADR-028).
    시설-지역 매핑의 어느 레벨이든 앞 5자리가 시군구."""
    return {r[0]: (r[1], r[2]) for r in c.execute(text("""
        SELECT DISTINCT ON (fm.hist_id) fm.hist_id, m.value, m.pct
          FROM mart.facility_area_map fm
          JOIN mart.access_metric m ON m.calc_run_id = :r AND m.adm_cd = left(fm.adm_cd, 5)
                                   AND m.metric_code = 'NET_OUT_12M_PER_1K'
         WHERE fm.stat_year = :y AND fm.hist_id = ANY(CAST(:ids AS bigint[]))
         ORDER BY fm.hist_id, fm.level"""), {"r": run_id, "y": y, "ids": ids})}


def net_out_of_areas(c: Connection, run_id: Any, cds: list[str]) -> dict[str, tuple[Any, Any]]:
    """지역(시군구·읍면동) → 그 시군구의 12개월 순유출(천 명당)·백분위 → {adm_cd: (값, 백분위)}."""
    rows = {r[0]: (r[1], r[2]) for r in c.execute(text("""
        SELECT adm_cd, value, pct FROM mart.access_metric
         WHERE calc_run_id = :r AND metric_code = 'NET_OUT_12M_PER_1K' AND adm_cd = ANY(CAST(:c AS text[]))"""),
        {"r": run_id, "c": sorted({cd[:5] for cd in cds})})}
    return {cd: rows[cd[:5]] for cd in cds if cd[:5] in rows}


def current_nearest(c: Connection, run_id: Any, y: int, level: int, scope: str) -> dict[str, float]:
    """범위 안 지역 → 지금 최근접 금융 우체국 거리."""
    return {r[0]: float(r[1]) for r in c.execute(text("""
        SELECT a.adm_cd, n.dist_m FROM mart.admin_area a
          JOIN mart.area_nearest n ON n.calc_run_id = :run AND n.adm_cd = a.adm_cd AND n.rank = 1
         WHERE a.stat_year = :y AND a.level = :lvl AND a.adm_cd LIKE :scope || '%'"""),
        {"run": run_id, "y": y, "lvl": level, "scope": scope})}


def sites_within(c: Connection, y: int, level: int, scope: str, radius_m: float) -> list[Row]:
    """후보지(지역 대표점) → 반경 안 지역과 거리 (후보지, 지역, 거리)."""
    return c.execute(text("""
        SELECT s.adm_cd, a.adm_cd, ST_Distance(s.rep_point_5179, a.rep_point_5179)
          FROM mart.admin_area s
          JOIN mart.admin_area a ON a.stat_year = s.stat_year AND a.level = s.level
                                AND a.adm_cd LIKE :scope || '%'
                                AND ST_DWithin(s.rep_point_5179, a.rep_point_5179, :r)
         WHERE s.stat_year = :y AND s.level = :lvl AND s.adm_cd LIKE :scope || '%'"""),
        {"y": y, "lvl": level, "scope": scope, "r": radius_m}).all()


def rep_points(c: Connection, y: int, cds: list[str]) -> dict[str, tuple[float, float]]:
    """지역 대표점 (위도, 경도)."""
    return {r[0]: (r[1], r[2]) for r in c.execute(text("""
        SELECT adm_cd, ST_Y(rep_point), ST_X(rep_point) FROM mart.admin_area
         WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": cds})}


def area_names(c: Connection, y: int, cds: list[str]) -> dict[str, str]:
    return {r[0]: r[1] for r in c.execute(text("""
        SELECT a.adm_cd, coalesce(pa.adm_nm || ' ', '') || a.adm_nm FROM mart.admin_area a
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE a.stat_year = :y AND a.adm_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": cds})}


def scope_name(c: Connection, y: int, scope: str) -> str | None:
    return c.execute(text("""SELECT adm_nm FROM mart.area_population WHERE stat_year = :y AND adm_cd = :s"""),
                     {"y": y, "s": scope}).scalar()
