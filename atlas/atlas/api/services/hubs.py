"""⑦ 생활 거점 — 우체국이 동네의 마지막 필수 거점인지 (약국·의원·은행 지점과 함께 판정, calc 09_life.sql).

- summary: 전국 합계(시군구 합)·자료 기준 시점·상위 지역
- facilities: 우체국별 대체 불가능성 순위 (facility_hub)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api.common import jsonable, meta_of, page_params, resolve_calc_run

LIFE_METRICS = ("POST_SOLE_HUB_PPLTN", "LIFE_DESERT_PPLTN", "CARE_DESERT_PPLTN", "HOLIDAY_CARE_GAP_PPLTN",
                "POPW_PHARMACY_DIST_M", "POPW_CLINIC_DIST_M")
SORTS = {"soleHub": "h.sole_hub_ppltn", "soleFin": "h.sole_fin_ppltn", "served": "h.served_ppltn"}


def care_status(c: Connection) -> dict[str, Any]:
    r = c.execute(text("""SELECT count(*) FILTER (WHERE kind = 'PHARMACY') AS pharmacy,
                                 count(*) FILTER (WHERE kind = 'CLINIC') AS clinic,
                                 count(*) FILTER (WHERE open_holiday) AS holiday_open,
                                 max(last_seen) AS as_of FROM mart.care_place""")).mappings().one()
    return jsonable({"pharmacy": r["pharmacy"], "clinic": r["clinic"], "holidayOpen": r["holiday_open"],
                     "asOf": r["as_of"]})


def summary(c: Connection, calc_run_id: str | None) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    rid, y = run["calc_run_id"], run["stat_year"]
    sums = dict(c.execute(text("""
        SELECT metric_code, sum(value) FROM mart.access_metric
         WHERE calc_run_id = :rid AND level = 2 AND metric_code = ANY(CAST(:m AS text[]))
           AND metric_code LIKE '%PPLTN' GROUP BY 1"""), {"rid": rid, "m": list(LIFE_METRICS)}).all())
    popw = c.execute(text("""
        SELECT sum(tot_ppltn * pharmacy_m) / nullif(sum(tot_ppltn) FILTER (WHERE pharmacy_m IS NOT NULL), 0) AS ph,
               sum(tot_ppltn * clinic_m) / nullif(sum(tot_ppltn) FILTER (WHERE clinic_m IS NOT NULL), 0) AS cl,
               sum(tot_ppltn) AS pop
          FROM mart.oa_nearest WHERE calc_run_id = :rid"""), {"rid": rid}).mappings().one()
    hub = c.execute(text("""SELECT count(*) FILTER (WHERE sole_hub_ppltn > 0) AS hubs,
                                   count(*) FILTER (WHERE sole_fin_ppltn > 0) AS fin_hubs, count(*) AS n
                              FROM mart.facility_hub WHERE calc_run_id = :rid"""), {"rid": rid}).mappings().one()
    top = [jsonable({"admCd": r[0], "admNm": r[1], "parentNm": r[2], "value": r[3], "totPpltn": r[4]})
           for r in c.execute(text("""
        SELECT m.adm_cd, a.adm_nm, pa.adm_nm, m.value, p.tot_ppltn
          FROM mart.access_metric m
          JOIN mart.admin_area a ON a.adm_cd = m.adm_cd AND a.stat_year = :y
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y
          LEFT JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = :y
         WHERE m.calc_run_id = :rid AND m.metric_code = 'POST_SOLE_HUB_PPLTN' AND m.level = 2 AND m.value > 0
         ORDER BY m.value DESC, m.adm_cd LIMIT 10"""), {"rid": rid, "y": y})]
    return {
        "meta": meta_of(run), "care": care_status(c),
        "available": bool(sums),
        "totals": jsonable({"soleHubPpltn": sums.get("POST_SOLE_HUB_PPLTN"), "lifeDesertPpltn": sums.get("LIFE_DESERT_PPLTN"),
                            "careDesertPpltn": sums.get("CARE_DESERT_PPLTN"),
                            "holidayCareGapPpltn": sums.get("HOLIDAY_CARE_GAP_PPLTN"),
                            "popwPharmacyM": round(float(popw["ph"]), 1) if popw["ph"] is not None else None,
                            "popwClinicM": round(float(popw["cl"]), 1) if popw["cl"] is not None else None,
                            "oaPpltn": popw["pop"]}),
        "facilities": jsonable({"withSoleHub": hub["hubs"], "withSoleFin": hub["fin_hubs"], "served": hub["n"]}),
        "topAreas": top,
    }


def facilities(c: Connection, calc_run_id: str | None, sido: str | None, sort: str, page: int, size: int) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    page, size, off = page_params(page, size, cap=100)
    order = SORTS.get(sort, SORTS["soleHub"])     # 정렬 열은 허용 목록에서만 (SQL 조립 안전)
    p = {"rid": run["calc_run_id"], "y": run["stat_year"], "sido": sido or None, "lim": size, "off": off}
    where = """h.calc_run_id = :rid
               AND (CAST(:sido AS text) IS NULL OR m.adm_cd LIKE CAST(:sido AS text) || '%')"""
    base = """FROM mart.facility_hub h
              JOIN mart.post_facility_hist f ON f.hist_id = h.hist_id
              LEFT JOIN mart.facility_area_map m ON m.hist_id = h.hist_id AND m.stat_year = :y AND m.level = 2
              LEFT JOIN mart.admin_area a ON a.adm_cd = m.adm_cd AND a.stat_year = :y
              LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y"""
    total = c.execute(text(f"SELECT count(*) {base} WHERE {where}"), p).scalar_one()
    rows = c.execute(text(f"""
        SELECT h.hist_id, f.name, f.addr, f.finance_time, ST_Y(f.geom) AS lat, ST_X(f.geom) AS lon,
               m.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm,
               h.served_ppltn, h.sole_fin_ppltn, h.sole_hub_ppltn, h.oa_count
          {base} WHERE {where}
         ORDER BY {order} DESC, h.served_ppltn DESC, h.hist_id LIMIT :lim OFFSET :off"""), p).mappings().all()
    return {"meta": meta_of(run), "page": page, "size": size, "total": total,
            "items": [jsonable({"histId": r["hist_id"], "name": r["name"], "addr": r["addr"],
                                "financeTime": r["finance_time"], "lat": r["lat"], "lon": r["lon"],
                                "admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentNm": r["parent_nm"],
                                "servedPpltn": r["served_ppltn"], "soleFinPpltn": r["sole_fin_ppltn"],
                                "soleHubPpltn": r["sole_hub_ppltn"], "oaCount": r["oa_count"]}) for r in rows]}


def facility_hub(c: Connection, hist_id: int) -> dict[str, Any] | None:
    """시설 카드용 — 최신 계산의 대체 불가능성 + 시설 주변 약국·의원·은행 최근접."""
    r = c.execute(text("""
        SELECT h.served_ppltn, h.sole_fin_ppltn, h.sole_hub_ppltn, h.oa_count,
               (SELECT count(*) + 1 FROM mart.facility_hub x WHERE x.calc_run_id = h.calc_run_id
                   AND x.sole_hub_ppltn > h.sole_hub_ppltn) AS rnk,
               (SELECT count(*) FROM mart.facility_hub x WHERE x.calc_run_id = h.calc_run_id AND x.sole_hub_ppltn > 0) AS n
          FROM mart.facility_hub h
         WHERE h.hist_id = :id AND h.calc_run_id = (SELECT calc_run_id FROM mart.calc_run WHERE status = 'DONE'
                                                     ORDER BY finished_at DESC NULLS LAST LIMIT 1)"""),
                  {"id": hist_id}).mappings().first()
    near = c.execute(text("""
        SELECT k.kind, k.name, k.div_name, k.open_holiday, round(CAST(k.d AS numeric)) AS dist_m
          FROM mart.post_facility_hist f
          CROSS JOIN LATERAL (
                (SELECT 'PHARMACY' AS kind, name, div_name, open_holiday, ST_Distance(geom_5179, f.geom_5179) AS d
                   FROM mart.care_place WHERE kind = 'PHARMACY' ORDER BY geom_5179 <-> f.geom_5179 LIMIT 1)
                UNION ALL
                (SELECT 'CLINIC', name, div_name, open_holiday, ST_Distance(geom_5179, f.geom_5179)
                   FROM mart.care_place WHERE kind = 'CLINIC' ORDER BY geom_5179 <-> f.geom_5179 LIMIT 1)
                UNION ALL
                (SELECT 'BANK', name, category, false, ST_Distance(geom_5179, f.geom_5179)
                   FROM mart.bank_place WHERE kind = 'BRANCH' ORDER BY geom_5179 <-> f.geom_5179 LIMIT 1)) k
         WHERE f.hist_id = :id"""), {"id": hist_id}).mappings().all()
    if not r and not near:
        return None
    return jsonable({
        "servedPpltn": r and r["served_ppltn"], "soleFinPpltn": r and r["sole_fin_ppltn"],
        "soleHubPpltn": r and r["sole_hub_ppltn"], "oaCount": r and r["oa_count"],
        "soleHubRank": r["rnk"] if r and r["sole_hub_ppltn"] else None, "soleHubOf": r and r["n"],
        "nearby": [{"kind": n["kind"], "name": n["name"], "divName": n["div_name"], "openHoliday": n["open_holiday"],
                    "distM": n["dist_m"]} for n in near],
    })
