"""전국 개요 조회 SQL — 계산 실행 하나(rid)의 결과 표를 집계 (흐름은 service.py, 집계 규칙은 domain/overview.py)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, RowMapping


def facility_counts(c: Connection, asof: Any) -> list[RowMapping]:
    """계산 시점 시설 종류별 수와 금융 가능 수."""
    return c.execute(text("""
        SELECT post_div, count(*) AS n, count(*) FILTER (WHERE fin_available) AS fin
          FROM mart.post_facility_hist
         WHERE valid_from <= :asof AND (valid_to IS NULL OR valid_to > :asof)
         GROUP BY post_div ORDER BY post_div"""), {"asof": asof}).mappings().all()


def area_distances(c: Connection, rid: Any, y: int, level: int) -> list[RowMapping]:
    """레벨의 지역별 최근접 금융 우체국 거리(d)·인구(pop)·65세 이상(aged)."""
    return c.execute(text("""
        SELECT m.value AS d, p.tot_ppltn AS pop, r.aged65_ppltn AS aged
          FROM mart.access_metric m
          JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = :y
          LEFT JOIN mart.area_resident_pop r ON r.adm_cd = m.adm_cd AND r.stat_year = :y
         WHERE m.calc_run_id = :rid AND m.metric_code = 'NEAREST_FIN_DIST_M' AND m.level = :lvl
           AND m.value IS NOT NULL"""), {"rid": rid, "y": y, "lvl": level}).mappings().all()


def top_areas(c: Connection, rid: Any, metric: str, level: int, y: int, n: int = 5) -> list[RowMapping]:
    """지표 값이 큰 지역 상위 n."""
    return c.execute(text("""
        SELECT m.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm, m.value
          FROM mart.access_metric m
          JOIN mart.admin_area a ON a.adm_cd = m.adm_cd AND a.stat_year = :y
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y
         WHERE m.calc_run_id = :rid AND m.metric_code = :m AND m.level = :lvl AND m.value IS NOT NULL
         ORDER BY m.value DESC, m.adm_cd LIMIT :n"""), {"rid": rid, "m": metric, "lvl": level, "y": y, "n": n}).mappings().all()


def kosis_totals(c: Connection, y: int) -> RowMapping:
    """주민등록인구(KOSIS) 시군구 합 — 기준 시점, 65세 이상, 전체."""
    return c.execute(text("""SELECT max(ref_period) AS period, sum(aged65_ppltn) AS aged, sum(tot_ppltn) AS tot
                             FROM mart.area_resident_pop WHERE stat_year = :y
                               AND adm_cd IN (SELECT adm_cd FROM mart.admin_area WHERE stat_year = :y AND level = 2)"""),
                     {"y": y}).mappings().one()


def oa_totals(c: Connection, rid: Any, far_m: float) -> RowMapping:
    """집계구 기준 전국 값 — 수, 인구, 인구 가중 거리, far_m 밖 인구."""
    return c.execute(text("""SELECT count(*) AS n, sum(tot_ppltn) AS pop,
                                    sum(tot_ppltn * dist_m) / nullif(sum(tot_ppltn), 0) AS popw,
                                    sum(tot_ppltn) FILTER (WHERE dist_m > :far) AS far_pop
                               FROM mart.oa_nearest WHERE calc_run_id = :rid"""), {"rid": rid, "far": far_m}).mappings().one()


def metric_sums(c: Connection, rid: Any, codes: tuple[str, ...]) -> dict[str, Any]:
    """시군구(레벨 2) 지표 합 — 계산하지 않은 지표는 키가 없음."""
    return dict(c.execute(text("""SELECT metric_code, sum(value) FROM mart.access_metric
                                   WHERE calc_run_id = :rid AND level = 2
                                     AND metric_code = ANY(CAST(:codes AS text[])) GROUP BY 1"""),
                          {"rid": rid, "codes": list(codes)}).all())


def road_totals(c: Connection, rid: Any, y: int, level: int) -> RowMapping:
    """도로 거리를 구한 지역의 인구 가중 도로·직선 거리와 운전 시간."""
    return c.execute(text("""
        SELECT count(*) AS n, sum(m.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_road,
               sum(s.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_straight,
               sum(t.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_min
          FROM mart.access_metric m
          JOIN mart.access_metric s ON s.calc_run_id = m.calc_run_id AND s.adm_cd = m.adm_cd AND s.metric_code = 'NEAREST_FIN_DIST_M'
          JOIN mart.access_metric t ON t.calc_run_id = m.calc_run_id AND t.adm_cd = m.adm_cd AND t.metric_code = 'NEAREST_FIN_DRIVE_MIN'
          JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = :y
         WHERE m.calc_run_id = :rid AND m.metric_code = 'NEAREST_FIN_ROAD_M' AND m.level = :lvl"""),
        {"rid": rid, "y": y, "lvl": level}).mappings().one()


def sole_hub_facilities(c: Connection, rid: Any) -> int:
    return c.execute(text("""SELECT count(*) FILTER (WHERE sole_hub_ppltn > 0) FROM mart.facility_hub
                              WHERE calc_run_id = :rid"""), {"rid": rid}).scalar()


def bank_grades(c: Connection, rid: Any) -> RowMapping:
    """은행 지점 폐쇄 영향 — 평가 지점 수, 높음 등급 수, 잃는 인구 합."""
    return c.execute(text("""SELECT count(*) AS n, count(*) FILTER (WHERE grade = 'HIGH') AS high,
                                    coalesce(sum(lost_ppltn), 0) AS lost
                               FROM mart.bank_impact WHERE calc_run_id = :rid"""), {"rid": rid}).mappings().one()
