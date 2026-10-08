"""은행 지점 조회 SQL — 지도 레이어, 폐쇄 영향평가 목록·상세·이용 주민 지도 (흐름·응답 모양은 service.py)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, RowMapping

_COLS = """b.place_id, p.name, b.brand, p.addr, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon, b.post_agent, b.adm_cd,
           a.adm_nm, pa.adm_nm AS parent_nm, b.catch_oa, b.catch_ppltn, b.catch_aged, b.same_brand_m, b.other_bank_m,
           b.post_m, b.popw_now_m, b.popw_alt_m, b.lost_ppltn, b.lost_aged, b.walk_now_m, b.walk_alt_m,
           b.walk_lost_ppltn, b.grade, b.reasons, b.rnk, b.n"""
_FROM = """FROM mart.bank_impact b
           JOIN mart.bank_place p ON p.place_id = b.place_id
           LEFT JOIN mart.admin_area a ON a.adm_cd = b.adm_cd AND a.stat_year = :y
           LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y"""   # 시도 이름(행정구역 표에는 시도 행 없음)
_IN_REGION = """b.calc_run_id = :r AND (CAST(:sido AS text) IS NULL OR b.adm_cd LIKE CAST(:sido AS text) || '%')
               AND (CAST(:sgg AS text) IS NULL OR b.adm_cd = CAST(:sgg AS text))"""


def places_in_bbox(c: Connection, x1: float, y1: float, x2: float, y2: float, atm: bool, size: int) -> list[RowMapping]:
    """대면 지점은 '지금 영업 중'으로 보는 목록(마지막 전수 수집 기준), ATM 은 수집한 그대로."""
    return c.execute(text("""
        SELECT place_id, name, category, brand, kind, addr, ST_Y(geom) AS lat, ST_X(geom) AS lon, last_seen FROM (
            SELECT place_id, name, category, brand, 'BRANCH' AS kind, addr, geom, last_seen FROM mart.bank_branch_current
            UNION ALL
            SELECT place_id, name, category, brand, kind, addr, geom, last_seen FROM mart.bank_place
             WHERE kind = 'ATM' AND CAST(:atm AS boolean)) b
         WHERE geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)
         ORDER BY place_id LIMIT :n"""), {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "atm": atm, "n": size}).mappings().all()


def walk_run(c: Connection, run_id: Any) -> RowMapping | None:
    return c.execute(text("""SELECT status, speed_mps, limit_m, graph, finished_at FROM mart.walk_run
                             WHERE calc_run_id = :r"""), {"r": run_id}).mappings().first()


def last_full_crawl(c: Connection) -> RowMapping | None:
    """마지막 은행 지점 전수 수집."""
    return c.execute(text("""SELECT started_at, stats->>'totalBranches' AS n FROM ops.collect_run
                             WHERE kind = 'KAKAO_BANK' AND status = 'DONE' AND scope LIKE 'FULL;%'
                             ORDER BY started_at DESC LIMIT 1""")).mappings().first()


def impact_summary(c: Connection, p: dict[str, Any]) -> RowMapping:
    """지역(시도·시군구) 안 등급별 지점 수와 인구 합 — 등급 필터와 무관."""
    return c.execute(text(f"""
        SELECT count(*) AS n, count(*) FILTER (WHERE grade = 'HIGH') AS high, count(*) FILTER (WHERE grade = 'MID') AS mid,
               count(*) FILTER (WHERE grade = 'LOW') AS low, coalesce(sum(lost_ppltn), 0) AS lost,
               coalesce(sum(walk_lost_ppltn), 0) AS walk_lost, coalesce(sum(catch_ppltn), 0) AS catch
          FROM mart.bank_impact b
         WHERE {_IN_REGION}"""), p).mappings().one()


def impact_page(c: Connection, p: dict[str, Any], order_by: str) -> tuple[int, list[RowMapping]]:
    """(조건에 맞는 지점 수, 한 페이지). order_by 는 service 의 고정 목록(SORTS)에서 고른 값."""
    where = f"""{_IN_REGION}
               AND (CAST(:grade AS text) IS NULL OR b.grade = CAST(:grade AS text))"""
    total = c.execute(text(f"SELECT count(*) FROM mart.bank_impact b WHERE {where}"), p).scalar_one()
    rows = c.execute(text(f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY {order_by}, b.place_id LIMIT :lim OFFSET :off"),
                     p).mappings().all()
    return total, rows


def impact_one(c: Connection, run: dict[str, Any], place_id: str) -> RowMapping | None:
    return c.execute(text(f"SELECT {_COLS} {_FROM} WHERE b.calc_run_id = :r AND b.place_id = :id"),
                     {"r": run["calc_run_id"], "y": run["stat_year"], "id": place_id}).mappings().first()


def alternatives(c: Connection, run: dict[str, Any], place_id: str) -> list[RowMapping]:
    """대체 창구 — 같은 은행 다음 지점, 다른 은행 지점 3곳, 금융 우체국 3곳 (지점 위치 기준)."""
    return c.execute(text("""
        WITH x AS (SELECT geom_5179, brand FROM mart.bank_place WHERE place_id = :id)
        (SELECT 'SAME_BANK' AS kind, b.name, b.brand AS sub, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
                round(CAST(ST_Distance(b.geom_5179, x.geom_5179) AS numeric)) AS dist_m
           FROM x, mart.bank_branch_current b WHERE b.brand = x.brand AND b.place_id <> :id
          ORDER BY b.geom_5179 <-> x.geom_5179 LIMIT 1)
        UNION ALL
        (SELECT 'OTHER_BANK', b.name, b.brand, ST_Y(b.geom), ST_X(b.geom),
                round(CAST(ST_Distance(b.geom_5179, x.geom_5179) AS numeric))
           FROM x, mart.bank_branch_current b JOIN mart.bank_brand bb ON bb.brand = b.brand AND bb.grp = 'BANK'
          WHERE b.brand <> x.brand ORDER BY b.geom_5179 <-> x.geom_5179 LIMIT 3)
        UNION ALL
        (SELECT 'POST', h.name, h.finance_time, ST_Y(h.geom), ST_X(h.geom),
                round(CAST(ST_Distance(h.geom_5179, x.geom_5179) AS numeric))
           FROM x, mart.post_facility_hist h
          WHERE h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof) AND h.fin_available AND NOT h.is_center
          ORDER BY h.geom_5179 <-> x.geom_5179 LIMIT 3)"""),
        {"id": place_id, "asof": run["facility_as_of"]}).mappings().all()


def alt_distance_bands(c: Connection, run_id: Any, place_id: str) -> list[RowMapping]:
    """이 지점을 쓰는 집계구를 대체 창구 거리대(1·2·5·10km)로 묶은 수와 인구."""
    return c.execute(text("""
        SELECT width_bucket(alt_m, ARRAY[1000, 2000, 5000, 10000]::real[]) AS band, count(*) AS oa,
               sum(coalesce(n.tot_ppltn, 0)) AS pop
          FROM mart.oa_bank ob JOIN mart.oa_nearest n ON n.calc_run_id = ob.calc_run_id AND n.oa_cd = ob.oa_cd
         WHERE ob.calc_run_id = :r AND ob.b1 = :id GROUP BY 1 ORDER BY 1"""), {"r": run_id, "id": place_id}).mappings().all()


def catchment(c: Connection, run: dict[str, Any], place_id: str) -> str:
    """이 지점이 가장 가까운 은행 지점인 집계구 FeatureCollection(text). 경계는 30m 단순화."""
    return c.execute(text("""
        SELECT CAST(json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                 'type', 'Feature', 'id', o.oa_cd,
                 'properties', json_build_object('admCd', o.oa_cd, 'admNm', '집계구 ' || right(o.oa_cd, 6),
                     'ppltn', n.tot_ppltn, 'nowM', round(CAST(ob.d1 AS numeric)), 'altM', round(CAST(ob.alt_m AS numeric)),
                     'aged', round(CAST(ob.aged AS numeric))),
                 'geometry', CAST(ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(o.geom_5179, 30), 4326), 5) AS json))
               ORDER BY o.oa_cd), CAST('[]' AS json))) AS text)
          FROM mart.oa_bank ob
          JOIN mart.oa_area o ON o.oa_cd = ob.oa_cd AND o.stat_year = :y
          JOIN mart.oa_nearest n ON n.calc_run_id = ob.calc_run_id AND n.oa_cd = ob.oa_cd
         WHERE ob.calc_run_id = :r AND ob.b1 = :id"""),
        {"r": run["calc_run_id"], "y": run["stat_year"], "id": place_id}).scalar_one()
