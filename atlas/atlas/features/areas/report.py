"""③ 지역 한 장 보고서 — 시군구 하나의 접근성·도보·생활 거점·은행 지점 영향·읍면동 표·방문 여건을 한 번에.

화면이 API 를 6~7번 부르지 않도록 서버에서 묶습니다. 계산 결과로 정해지는 부분은 Redis 에
(calc_run, 도보 계산 시각) 키로 캐시하고, 날마다 바뀌는 방문 여건만 매번 붙입니다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from atlas.calc.runs import meta_of, resolve_calc_run, walk_finished_at
from atlas.core import cache
from atlas.core.serial import jsonable
from atlas.domain.errors import DomainError, Invalid, NotFound
from atlas.features.areas import queries as q

# 보고서에 싣는 지표 — 화면 순서대로 (없는 지표는 건너뜀)
KEY_METRICS = ["POPW_FIN_DIST_M", "FAR2KM_SHARE", "AGED65_FAR_PPLTN", "NEAREST_FIN_DRIVE_MIN", "POPW_FIN_WALK_M",
               "WALK30_NO_FIN_SHARE", "WALK30_NO_CASH_PPLTN", "FIN_DESERT_PPLTN", "POST_SOLE_HUB_PPLTN",
               "CARE_DESERT_PPLTN", "HOLIDAY_CARE_GAP_PPLTN", "ACCESS_GAP_SCORE"]
EMD_METRICS = ["POPW_FIN_DIST_M", "FAR2KM_SHARE", "WALK30_NO_FIN_SHARE", "AGED65_RATIO"]


def report(c: Connection, adm_cd: str, calc_run_id: str | None) -> dict[str, Any]:
    if len(adm_cd) != 5 or not adm_cd.isdigit():
        raise Invalid("지역 보고서는 시군구(5자리 코드) 단위입니다.")
    run = resolve_calc_run(c, calc_run_id)
    walk_at = walk_finished_at(c, run["calc_run_id"])
    key = f"report:{run['calc_run_id']}:{walk_at.isoformat() if walk_at else '-'}:{adm_cd}"
    if cached := cache.get(key):
        body = json.loads(cached)
    else:
        body = _static(c, adm_cd, run, walk_at)
        cache.set(key, json.dumps(body, ensure_ascii=False), ttl=24 * 3600)
    try:
        from atlas.features.visit import area_outlook

        body["visit"] = area_outlook(c, adm_cd)
    except DomainError:
        body["visit"] = None                       # 예보를 아직 받지 않았으면 그 칸만 비움
    return body


def _static(c: Connection, adm_cd: str, run: dict[str, Any], walk_at: Any) -> dict[str, Any]:
    area = q.report_area(c, run, adm_cd)
    if not area:
        raise NotFound("AREA_NOT_FOUND", f"시군구 {adm_cd} ({run['stat_year']}년) 가 없습니다.")
    by = {m["metric_code"]: m for m in q.report_metrics(c, run, adm_cd, KEY_METRICS)}   # 핵심 지표 + 전국 시군구 중앙값
    posts = q.report_posts(c, run, adm_cd)
    fac_n = q.report_facility_counts(c, run, adm_cd)
    banks = q.report_banks(c, run, adm_cd)
    emds = q.report_emds(c, run, adm_cd, EMD_METRICS)

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
