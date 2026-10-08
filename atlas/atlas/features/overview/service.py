"""전국 개요 — 개요 화면의 큰 숫자·분포·취약 지역 (계산 실행 하나 기준, 데이터 버전 키로 캐시)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from atlas.calc.runs import data_version, meta_of, resolve_calc_run
from atlas.core import cache
from atlas.core.serial import jsonable
from atlas.domain.overview import distance_summary
from atlas.domain.params import far_meters
from atlas.domain.rules import POST_DIV_LABEL
from atlas.features.overview import queries as q

TTL_S = 3600


def overview(c: Connection, calc_run_id: str | None) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    key = f"overview:{data_version(c, run)}"
    if hit := cache.get(key):
        return json.loads(hit)
    rid, y = run["calc_run_id"], run["stat_year"]
    fine = max(int(x) for x in run["params"].get("levels", [2]))      # 가장 세밀한 레벨 기준 인구 가중 거리·거리대
    far_m = far_meters(run["params"])
    fac = q.facility_counts(c, run["facility_as_of"])
    dist = q.area_distances(c, rid, y, fine)
    kosis = q.kosis_totals(c, y)
    oa = q.oa_totals(c, rid, far_m)                                     # ① 집계구 (읍면동 대표점보다 거주 분포를 잘 반영)
    gap = q.metric_sums(c, rid, ("POST_ONLY_PPLTN", "FIN_DESERT_PPLTN"))   # ④ 금융 공백
    road = q.road_totals(c, rid, y, fine)                               # ② 도로 거리
    life = q.metric_sums(c, rid, ("POST_SOLE_HUB_PPLTN", "LIFE_DESERT_PPLTN", "CARE_DESERT_PPLTN",
                                  "HOLIDAY_CARE_GAP_PPLTN"))             # ⑦ 생활 거점 — 약국·의원 자료를 넣은 계산만
    walk = q.metric_sums(c, rid, ("WALK30_NO_FIN_PPLTN", "WALK30_NO_CASH_PPLTN"))   # ② 걸어서 — 도보 계산 후만
    banks = q.bank_grades(c, rid)                                       # ① 은행 지점 폐쇄 영향
    ds = distance_summary(dist, far_m, bool(kosis["aged"]))
    tot_pop, wavg, far_pop, far_aged = ds["totPop"], ds["weightedAvgDistM"], ds["farPpltn"], ds["farAged"]
    out = jsonable({
        "facilities": [{"postDiv": f["post_div"], "label": POST_DIV_LABEL.get(f["post_div"], "기타"),
                        "count": f["n"], "finCount": f["fin"]} for f in fac],
        "facilityTotal": sum(f["n"] for f in fac),
        "finTotal": sum(f["fin"] for f in fac),
        "level": fine,
        "areaCount": len(dist),
        "weightedAvgDistM": round(wavg, 1) if wavg is not None else None,
        "farKm": far_m / 1000,
        "farPpltn": far_pop, "farShare": round(100 * far_pop / tot_pop, 1) if tot_pop else None,
        "distanceBands": ds["bands"],
        "kosis": ({"refPeriod": kosis["period"], "aged65": kosis["aged"], "totPpltn": kosis["tot"],
                   "aged65Ratio": round(100 * kosis["aged"] / kosis["tot"], 1) if kosis["tot"] else None,
                   "aged65Far": far_aged,
                   "aged65FarShare": round(100 * far_aged / kosis["aged"], 1) if kosis["aged"] else None}
                  if kosis["aged"] else None),
        "topGap": _top(c, rid, "ACCESS_GAP_SCORE", y), "topAgedFar": _top(c, rid, "AGED65_FAR_PPLTN", y),
        "topPostOnly": _top(c, rid, "POST_ONLY_PPLTN", y),
        "oa": ({"count": oa["n"], "ppltn": oa["pop"], "popwDistM": round(float(oa["popw"]), 1),
                "farPpltn": oa["far_pop"] or 0, "farShare": round(100 * (oa["far_pop"] or 0) / oa["pop"], 1)}
               if oa["n"] else None),
        "finGap": ({"postOnlyPpltn": gap.get("POST_ONLY_PPLTN"), "desertPpltn": gap.get("FIN_DESERT_PPLTN")}
                   if gap else None),
        "road": ({"areas": road["n"], "popwRoadM": round(float(road["popw_road"]), 1),
                  "popwStraightM": round(float(road["popw_straight"]), 1),
                  "popwDriveMin": round(float(road["popw_min"]), 1)} if road["n"] else None),
        "life": ({"soleHubPpltn": life.get("POST_SOLE_HUB_PPLTN"), "lifeDesertPpltn": life.get("LIFE_DESERT_PPLTN"),
                  "careDesertPpltn": life.get("CARE_DESERT_PPLTN"),
                  "holidayCareGapPpltn": life.get("HOLIDAY_CARE_GAP_PPLTN"),
                  "soleHubFacilities": q.sole_hub_facilities(c, rid)}
                 if life else None),
        "topSoleHub": _top(c, rid, "POST_SOLE_HUB_PPLTN", y) if life else [],
        "walk": ({"noFinPpltn": walk.get("WALK30_NO_FIN_PPLTN"), "noCashPpltn": walk.get("WALK30_NO_CASH_PPLTN"),
                  "noFinShare": round(100 * float(walk["WALK30_NO_FIN_PPLTN"]) / oa["pop"], 1) if oa["n"] and walk.get("WALK30_NO_FIN_PPLTN") is not None else None}
                 if walk else None),
        "banks": ({"branches": banks["n"], "high": banks["high"], "lostPpltn": banks["lost"]} if banks["n"] else None),
        "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=TTL_S)
    return out


def _top(c: Connection, rid: Any, metric: str, y: int) -> list[dict[str, Any]]:
    """시군구 상위 5곳."""
    return [jsonable({"admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentNm": r["parent_nm"], "value": r["value"]})
            for r in q.top_areas(c, rid, metric, 2, y)]
