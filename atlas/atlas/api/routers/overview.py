"""전국 개요 — 개요 화면의 큰 숫자·분포·취약 지역 (최신 calc_run 기준)."""
from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import text

from atlas.api import cache
from atlas.api.common import jsonable, meta_of, resolve_calc_run
from atlas.core.db import get_engine
from atlas.domain.rules import POST_DIV_LABEL

router = APIRouter(prefix="/overview", tags=["overview"])

BANDS = [(0, 1000, "1km 이내"), (1000, 2000, "1–2km"), (2000, 3000, "2–3km"), (3000, 5000, "3–5km"),
         (5000, None, "5km 넘음")]


@router.get("", summary="전국 개요 — 시설·거리 분포·고령인구·취약 지역 (최신 calc_run)")
def overview(calcRunId: str | None = None):
    with get_engine().connect() as c:
        run = resolve_calc_run(c, calcRunId)
        key = f"overview:{run['calc_run_id']}"
        if hit := cache.get(key):
            return json.loads(hit)
        rid, y = run["calc_run_id"], run["stat_year"]
        levels = [int(x) for x in run["params"].get("levels", [2])]
        fine = max(levels)
        fac = c.execute(text("""
            SELECT post_div, count(*) AS n, count(*) FILTER (WHERE fin_available) AS fin
              FROM mart.post_facility_hist
             WHERE valid_from <= :asof AND (valid_to IS NULL OR valid_to > :asof)
             GROUP BY post_div ORDER BY post_div"""), {"asof": run["facility_as_of"]}).mappings().all()
        # 가장 세밀한 레벨 기준 인구 가중 거리·거리대별 인구
        dist = c.execute(text("""
            SELECT m.value AS d, p.tot_ppltn AS pop, r.aged65_ppltn AS aged
              FROM mart.access_metric m
              JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = :y
              LEFT JOIN mart.area_resident_pop r ON r.adm_cd = m.adm_cd AND r.stat_year = :y
             WHERE m.calc_run_id = :rid AND m.metric_code = 'NEAREST_FIN_DIST_M' AND m.level = :lvl
               AND m.value IS NOT NULL"""), {"rid": rid, "y": y, "lvl": fine}).mappings().all()
        top_gap = _top(c, rid, "ACCESS_GAP_SCORE", 2, y)
        top_far = _top(c, rid, "AGED65_FAR_PPLTN", 2, y)
        kosis = c.execute(text("""SELECT max(ref_period) AS period, sum(aged65_ppltn) AS aged, sum(tot_ppltn) AS tot
                                  FROM mart.area_resident_pop WHERE stat_year = :y
                                    AND adm_cd IN (SELECT adm_cd FROM mart.admin_area WHERE stat_year = :y AND level = 2)"""),
                          {"y": y}).mappings().one()
        far_m = float(run["params"].get("farKm", 2)) * 1000
        # ① 집계구 기준 전국 값 (읍면동 대표점보다 거주 분포를 잘 반영)
        oa = c.execute(text("""SELECT count(*) AS n, sum(tot_ppltn) AS pop,
                                      sum(tot_ppltn * dist_m) / nullif(sum(tot_ppltn), 0) AS popw,
                                      sum(tot_ppltn) FILTER (WHERE dist_m > :far) AS far_pop
                                 FROM mart.oa_nearest WHERE calc_run_id = :rid"""), {"rid": rid, "far": far_m}).mappings().one()
        # ④ 금융 공백 (시군구 합) · ② 도로 거리 (가장 세밀한 레벨, 인구 가중)
        gap = dict(c.execute(text("""SELECT metric_code, sum(value) FROM mart.access_metric
                                      WHERE calc_run_id = :rid AND level = 2
                                        AND metric_code IN ('POST_ONLY_PPLTN', 'FIN_DESERT_PPLTN') GROUP BY 1"""),
                             {"rid": rid}).all())
        road = c.execute(text("""
            SELECT count(*) AS n, sum(m.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_road,
                   sum(s.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_straight,
                   sum(t.value * p.tot_ppltn) / nullif(sum(p.tot_ppltn), 0) AS popw_min
              FROM mart.access_metric m
              JOIN mart.access_metric s ON s.calc_run_id = m.calc_run_id AND s.adm_cd = m.adm_cd AND s.metric_code = 'NEAREST_FIN_DIST_M'
              JOIN mart.access_metric t ON t.calc_run_id = m.calc_run_id AND t.adm_cd = m.adm_cd AND t.metric_code = 'NEAREST_FIN_DRIVE_MIN'
              JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = :y
             WHERE m.calc_run_id = :rid AND m.metric_code = 'NEAREST_FIN_ROAD_M' AND m.level = :lvl"""),
            {"rid": rid, "y": y, "lvl": fine}).mappings().one()
        top_post_only = _top(c, rid, "POST_ONLY_PPLTN", 2, y)

    tot_pop = sum(r["pop"] or 0 for r in dist)
    wavg = sum(float(r["d"]) * (r["pop"] or 0) for r in dist) / tot_pop if tot_pop else None
    bands = []
    for lo, hi, label in BANDS:
        rows = [r for r in dist if float(r["d"]) >= lo and (hi is None or float(r["d"]) < hi)]
        pop = sum(r["pop"] or 0 for r in rows)
        aged = sum(r["aged"] or 0 for r in rows)
        bands.append({"label": label, "areas": len(rows), "ppltn": pop,
                      "share": round(100 * pop / tot_pop, 1) if tot_pop else None,
                      "aged65": aged if kosis["aged"] else None})
    far_pop = sum(r["pop"] or 0 for r in dist if float(r["d"]) > 2000)
    far_aged = sum(r["aged"] or 0 for r in dist if float(r["d"]) > 2000)
    out = jsonable({
        "facilities": [{"postDiv": f["post_div"], "label": POST_DIV_LABEL.get(f["post_div"], "기타"),
                        "count": f["n"], "finCount": f["fin"]} for f in fac],
        "facilityTotal": sum(f["n"] for f in fac),
        "finTotal": sum(f["fin"] for f in fac),
        "level": fine,
        "areaCount": len(dist),
        "weightedAvgDistM": round(wavg, 1) if wavg is not None else None,
        "farPpltn": far_pop, "farShare": round(100 * far_pop / tot_pop, 1) if tot_pop else None,
        "distanceBands": bands,
        "kosis": ({"refPeriod": kosis["period"], "aged65": kosis["aged"], "totPpltn": kosis["tot"],
                   "aged65Ratio": round(100 * kosis["aged"] / kosis["tot"], 1) if kosis["tot"] else None,
                   "aged65Far": far_aged,
                   "aged65FarShare": round(100 * far_aged / kosis["aged"], 1) if kosis["aged"] else None}
                  if kosis["aged"] else None),
        "topGap": top_gap, "topAgedFar": top_far, "topPostOnly": top_post_only,
        "oa": ({"count": oa["n"], "ppltn": oa["pop"], "popwDistM": round(float(oa["popw"]), 1),
                "farPpltn": oa["far_pop"] or 0, "farShare": round(100 * (oa["far_pop"] or 0) / oa["pop"], 1)}
               if oa["n"] else None),
        "finGap": ({"postOnlyPpltn": gap.get("POST_ONLY_PPLTN"), "desertPpltn": gap.get("FIN_DESERT_PPLTN")}
                   if gap else None),
        "road": ({"areas": road["n"], "popwRoadM": round(float(road["popw_road"]), 1),
                  "popwStraightM": round(float(road["popw_straight"]), 1),
                  "popwDriveMin": round(float(road["popw_min"]), 1)} if road["n"] else None),
        "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=3600)
    return out


def _top(c, rid, metric: str, level: int, y: int, n: int = 5) -> list[dict]:
    rows = c.execute(text("""
        SELECT m.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm, m.value
          FROM mart.access_metric m
          JOIN mart.admin_area a ON a.adm_cd = m.adm_cd AND a.stat_year = :y
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y
         WHERE m.calc_run_id = :rid AND m.metric_code = :m AND m.level = :lvl AND m.value IS NOT NULL
         ORDER BY m.value DESC, m.adm_cd LIMIT :n"""), {"rid": rid, "m": metric, "lvl": level, "y": y, "n": n}).mappings().all()
    return [jsonable({"admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentNm": r["parent_nm"], "value": r["value"]})
            for r in rows]
