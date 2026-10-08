"""③ 지역 한 장 보고서 — 시군구 하나의 접근성·도보·생활 거점·은행 지점 영향·읍면동 표·방문 여건을 한 번에.

화면이 API 를 6~7번 부르지 않도록 서버에서 묶습니다. 계산 결과로 정해지는 부분은 Redis 에
(calc_run, 도보 계산 시각) 키로 캐시하고, 날마다 바뀌는 방문 여건만 매번 붙입니다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api import cache
from atlas.api.common import bad_request, jsonable, meta_of, not_found, resolve_calc_run
from atlas.api.errors import ApiError

# 보고서에 싣는 지표 — 화면 순서대로 (없는 지표는 건너뜀)
KEY_METRICS = ["POPW_FIN_DIST_M", "FAR2KM_SHARE", "AGED65_FAR_PPLTN", "NEAREST_FIN_DRIVE_MIN", "POPW_FIN_WALK_M",
               "WALK30_NO_FIN_SHARE", "WALK30_NO_CASH_PPLTN", "FIN_DESERT_PPLTN", "POST_SOLE_HUB_PPLTN",
               "CARE_DESERT_PPLTN", "HOLIDAY_CARE_GAP_PPLTN", "ACCESS_GAP_SCORE"]
EMD_METRICS = ["POPW_FIN_DIST_M", "FAR2KM_SHARE", "WALK30_NO_FIN_SHARE", "AGED65_RATIO"]


def report(c: Connection, adm_cd: str, calc_run_id: str | None) -> dict[str, Any]:
    if len(adm_cd) != 5 or not adm_cd.isdigit():
        raise bad_request("지역 보고서는 시군구(5자리 코드) 단위입니다.")
    run = resolve_calc_run(c, calc_run_id)
    walk_at = c.execute(text("SELECT finished_at FROM mart.walk_run WHERE calc_run_id = :r AND status = 'DONE'"),
                        {"r": run["calc_run_id"]}).scalar()
    key = f"report:{run['calc_run_id']}:{walk_at.isoformat() if walk_at else '-'}:{adm_cd}"
    if cached := cache.get(key):
        body = json.loads(cached)
    else:
        body = _static(c, adm_cd, run, walk_at)
        cache.set(key, json.dumps(body, ensure_ascii=False), ttl=24 * 3600)
    try:
        from atlas.api.services.visit import area_outlook

        body["visit"] = area_outlook(c, adm_cd)
    except ApiError:
        body["visit"] = None                       # 예보를 아직 받지 않았으면 그 칸만 비움
    return body


def _static(c: Connection, adm_cd: str, run: dict[str, Any], walk_at: Any) -> dict[str, Any]:
    p = {"r": run["calc_run_id"], "y": run["stat_year"], "cd": adm_cd, "asof": run["facility_as_of"]}
    area = c.execute(text("""
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
         WHERE a.adm_cd = :cd AND a.stat_year = :y AND a.level = 2"""), p).mappings().first()
    if not area:
        raise not_found("AREA_NOT_FOUND", f"시군구 {adm_cd} ({run['stat_year']}년) 가 없습니다.")

    # 핵심 지표 + 전국 시군구 중앙값(비교 기준)
    metrics = c.execute(text("""
        SELECT d.metric_code, d.name_ko, d.unit, d.higher_is_worse, m.value, m.rnk, m.n, m.pct,
               (SELECT round(CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY x.value) AS numeric), 2) FROM mart.access_metric x
                 WHERE x.calc_run_id = m.calc_run_id AND x.metric_code = m.metric_code AND x.level = 2) AS median
          FROM mart.access_metric m JOIN mart.metric_def d ON d.metric_code = m.metric_code
         WHERE m.calc_run_id = :r AND m.adm_cd = :cd AND m.metric_code = ANY(:codes)"""),
        {**p, "codes": KEY_METRICS}).mappings().all()
    by = {m["metric_code"]: m for m in metrics}

    posts = c.execute(text("""
        SELECT h.hist_id, h.name, h.post_div, h.finance_time, h.post365_yn, ST_Y(h.geom) AS lat, ST_X(h.geom) AS lon,
               fh.served_ppltn, fh.sole_fin_ppltn, fh.sole_hub_ppltn
          FROM mart.facility_area_map fm
          JOIN mart.post_facility_hist h ON h.hist_id = fm.hist_id
          LEFT JOIN mart.facility_hub fh ON fh.calc_run_id = :r AND fh.hist_id = h.hist_id
         WHERE fm.stat_year = :y AND fm.level = 2 AND fm.adm_cd = :cd AND h.fin_available AND NOT h.is_center
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
         ORDER BY coalesce(fh.sole_hub_ppltn, 0) DESC, coalesce(fh.sole_fin_ppltn, 0) DESC, h.name"""), p).mappings().all()
    fac_n = c.execute(text("""
        SELECT count(*) AS all_n, count(*) FILTER (WHERE h.fin_available AND NOT h.is_center) AS fin_n,
               count(*) FILTER (WHERE h.post365_yn = 'Y') AS c365
          FROM mart.facility_area_map fm JOIN mart.post_facility_hist h ON h.hist_id = fm.hist_id
         WHERE fm.stat_year = :y AND fm.level = 2 AND fm.adm_cd = :cd
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)"""), p).mappings().one()

    banks = c.execute(text("""
        SELECT b.place_id, bp.name, b.brand, b.grade, b.reasons, b.catch_ppltn, b.lost_ppltn, b.walk_lost_ppltn
          FROM mart.bank_impact b JOIN mart.bank_place bp ON bp.place_id = b.place_id
         WHERE b.calc_run_id = :r AND b.adm_cd = :cd
         ORDER BY b.lost_ppltn DESC, b.catch_ppltn DESC"""), p).mappings().all()

    # 읍면동 표 + 작은 지도(30~200m 단순화 경계) — 지도 SDK 없이 SVG 로 그려 인쇄에도 그대로
    emds = c.execute(text("""
        SELECT e.adm_cd, e.adm_nm, p.tot_ppltn,
               jsonb_object_agg(m.metric_code, m.value) FILTER (WHERE m.metric_code IS NOT NULL) AS vals,
               CAST(ST_AsGeoJSON(coalesce(e.geom_simple, e.geom), 4) AS json) AS geom
          FROM mart.admin_area e
          LEFT JOIN mart.area_population p ON p.adm_cd = e.adm_cd AND p.stat_year = e.stat_year
          LEFT JOIN mart.access_metric m ON m.calc_run_id = :r AND m.adm_cd = e.adm_cd AND m.metric_code = ANY(:codes)
         WHERE e.stat_year = :y AND e.level = 3 AND e.parent_cd = :cd
         GROUP BY e.adm_cd, e.adm_nm, p.tot_ppltn, e.geom_simple, e.geom
         ORDER BY e.adm_cd"""), {**p, "codes": EMD_METRICS}).mappings().all()

    return {
        "area": jsonable({"admCd": area["adm_cd"], "admNm": area["adm_nm"], "parentCd": area["parent_cd"],
                          "parentNm": area["parent_nm"], "areaKm2": area["area_km2"], "totPpltn": area["tot_ppltn"],
                          "aged65Ppltn": area["aged65_ppltn"], "aged65Ratio": area["aged65_ratio"],
                          "kosisPeriod": area["ref_period"], "emdCount": area["emd_n"],
                          "bbox": [area["minx"], area["miny"], area["maxx"], area["maxy"]]}),
        "metrics": [jsonable({"code": k, "name": by[k]["name_ko"], "unit": by[k]["unit"], "higherIsWorse": by[k]["higher_is_worse"],
                              "value": by[k]["value"], "rank": by[k]["rnk"], "rankOf": by[k]["n"], "percentile": by[k]["pct"],
                              "median": by[k]["median"]}) for k in KEY_METRICS if k in by],
        "facilities": jsonable({"all": fac_n["all_n"], "fin": fac_n["fin_n"], "c365": fac_n["c365"]}),
        "posts": [jsonable({"histId": r["hist_id"], "name": r["name"], "postDiv": r["post_div"], "financeTime": r["finance_time"],
                            "has365": r["post365_yn"] == "Y", "lat": r["lat"], "lon": r["lon"], "servedPpltn": r["served_ppltn"],
                            "soleFinPpltn": r["sole_fin_ppltn"], "soleHubPpltn": r["sole_hub_ppltn"]}) for r in posts],
        "banks": {"branches": len(banks),
                  "byGrade": {g: sum(1 for b in banks if b["grade"] == g) for g in ("HIGH", "MID", "LOW")},
                  "lostPpltn": sum(b["lost_ppltn"] for b in banks),
                  "top": [jsonable({"placeId": b["place_id"], "name": b["name"], "brand": b["brand"], "grade": b["grade"],
                                    "reasons": list(b["reasons"] or []), "catchPpltn": b["catch_ppltn"],
                                    "lostPpltn": b["lost_ppltn"], "walkLostPpltn": b["walk_lost_ppltn"]})
                          for b in banks[:8]]},
        "emds": [jsonable({"admCd": e["adm_cd"], "admNm": e["adm_nm"], "totPpltn": e["tot_ppltn"],
                           "values": e["vals"] or {}, "geometry": e["geom"]}) for e in emds],
        "walk": jsonable({"finishedAt": walk_at}) if walk_at else None,
        "meta": meta_of(run, generatedFor=adm_cd),
    }
