"""① 은행 지점 폐쇄 영향평가 — 목록(순위·필터)·지점 상세(대체 창구)·이용 주민 지도. 계산은 calc/11_bank_impact.sql 과 walk."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.calc.runs import meta_of, resolve_calc_run

from atlas.core.serial import jsonable

from atlas.domain.params import page_params
from atlas.domain.errors import Invalid, NotFound

SORTS = {"lost": "b.lost_ppltn DESC, b.catch_ppltn DESC", "catch": "b.catch_ppltn DESC",
         "aged": "coalesce(b.catch_aged, 0) DESC", "walk": "coalesce(b.walk_lost_ppltn, 0) DESC, b.lost_ppltn DESC",
         "far": "coalesce(b.same_brand_m, 1e9) DESC"}
REASONS = {"NO_ALT_2KM": "지금은 2km 안에 이 지점이 있는데, 문을 닫으면 2km 안에 다른 은행도 은행 업무를 하는 우체국도 없는 주민이 있음",
           "NO_ALT_WALK30": "지금은 걸어서 30분 안에 이 지점이 있는데, 문을 닫으면 30분 안에 대체 창구가 없는 주민이 있음",
           "SAME_BANK_10KM": "같은 은행의 다음 지점이 10km 넘게 떨어져 있음",
           "AGED_20": "이 지점을 쓰는 주민의 20% 이상이 65세 이상(추정)"}
RULE = ("BANK-IMPACT-1 — 높음: 대체 창구가 2km 안에 없는 주민 1,000명 이상, 또는 그런 주민이 있으면서 같은 은행 다음 지점이 "
        "10km 밖이거나 고령 비율 20% 이상 / 보통: 위 요인 중 하나 / 낮음: 없음. 2026 은행 점포폐쇄 공동절차 개정 내용을 참고한 "
        "분석용 기준이며 공식 사전영향평가가 아닙니다.")
_COLS = """b.place_id, p.name, b.brand, p.addr, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon, b.post_agent, b.adm_cd,
           a.adm_nm, pa.adm_nm AS parent_nm, b.catch_oa, b.catch_ppltn, b.catch_aged, b.same_brand_m, b.other_bank_m,
           b.post_m, b.popw_now_m, b.popw_alt_m, b.lost_ppltn, b.lost_aged, b.walk_now_m, b.walk_alt_m,
           b.walk_lost_ppltn, b.grade, b.reasons, b.rnk, b.n"""
_FROM = """FROM mart.bank_impact b
           JOIN mart.bank_place p ON p.place_id = b.place_id
           LEFT JOIN mart.admin_area a ON a.adm_cd = b.adm_cd AND a.stat_year = :y
           LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = :y"""   # 시도 이름(행정구역 표에는 시도 행 없음)


def _item(r: Any) -> dict[str, Any]:
    return jsonable({
        "placeId": r["place_id"], "name": r["name"], "brand": r["brand"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"],
        "postAgent": r["post_agent"], "admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentNm": r["parent_nm"],
        "catchOa": r["catch_oa"], "catchPpltn": r["catch_ppltn"], "catchAged": r["catch_aged"],
        "sameBrandM": r["same_brand_m"], "otherBankM": r["other_bank_m"], "postM": r["post_m"],
        "popwNowM": r["popw_now_m"], "popwAltM": r["popw_alt_m"], "lostPpltn": r["lost_ppltn"], "lostAged": r["lost_aged"],
        "walkNowM": r["walk_now_m"], "walkAltM": r["walk_alt_m"], "walkLostPpltn": r["walk_lost_ppltn"],
        "grade": r["grade"], "reasons": list(r["reasons"] or []), "rank": r["rnk"], "rankOf": r["n"]})


def _walk_meta(c: Connection, run_id: Any) -> dict[str, Any] | None:
    w = c.execute(text("""SELECT status, speed_mps, limit_m, graph, finished_at FROM mart.walk_run
                          WHERE calc_run_id = :r"""), {"r": run_id}).mappings().first()
    if not w or w["status"] != "DONE":
        return None
    g = w["graph"] or {}
    return jsonable({"speedMps": w["speed_mps"], "limitM": w["limit_m"], "finishedAt": w["finished_at"],
                     "osmLastModified": g.get("osmLastModified"), "vertices": g.get("vertices")})


def _bank_list_meta(c: Connection) -> dict[str, Any]:
    r = c.execute(text("""SELECT started_at, stats->>'totalBranches' AS n FROM ops.collect_run
                          WHERE kind = 'KAKAO_BANK' AND status = 'DONE' AND scope LIKE 'FULL;%'
                          ORDER BY started_at DESC LIMIT 1""")).mappings().first()
    return jsonable({"fullCrawlAt": r and r["started_at"], "assumption":
                     "우체국 은행대리업: 보도된 '국내 14개 시중·지방은행 모두'를 은행 전체로 가정(은행별 명단 미확인), "
                     "금융 우체국 전체에서 입출금 가능으로 봄."})


def list_impact(c: Connection, calc_run_id: str | None, sido: str | None, sgg: str | None, grade: str | None,
                sort: str, page: int, size: int) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    if sort not in SORTS:
        raise Invalid(f"sort 는 {', '.join(SORTS)} 중 하나입니다.")
    page, size, offset = page_params(page, size, cap=100)
    where = """b.calc_run_id = :r AND (CAST(:sido AS text) IS NULL OR b.adm_cd LIKE CAST(:sido AS text) || '%')
               AND (CAST(:sgg AS text) IS NULL OR b.adm_cd = CAST(:sgg AS text))
               AND (CAST(:grade AS text) IS NULL OR b.grade = CAST(:grade AS text))"""
    p = {"r": run["calc_run_id"], "y": run["stat_year"], "sido": sido, "sgg": sgg, "grade": grade,
         "lim": size, "off": offset}
    summary = c.execute(text("""
        SELECT count(*) AS n, count(*) FILTER (WHERE grade = 'HIGH') AS high, count(*) FILTER (WHERE grade = 'MID') AS mid,
               count(*) FILTER (WHERE grade = 'LOW') AS low, coalesce(sum(lost_ppltn), 0) AS lost,
               coalesce(sum(walk_lost_ppltn), 0) AS walk_lost, coalesce(sum(catch_ppltn), 0) AS catch
          FROM mart.bank_impact b
         WHERE b.calc_run_id = :r AND (CAST(:sido AS text) IS NULL OR b.adm_cd LIKE CAST(:sido AS text) || '%')
           AND (CAST(:sgg AS text) IS NULL OR b.adm_cd = CAST(:sgg AS text))"""), p).mappings().one()
    total = c.execute(text(f"SELECT count(*) FROM mart.bank_impact b WHERE {where}"), p).scalar_one()
    rows = c.execute(text(f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY {SORTS[sort]}, b.place_id LIMIT :lim OFFSET :off"),
                     p).mappings().all()
    if summary["n"] == 0 and not (sido or sgg):
        raise NotFound("BANK_IMPACT_NOT_FOUND", "은행 지점 영향평가 결과가 없습니다 — 은행 지점 수집(make banks-full) 뒤 지표를 다시 계산하세요.")
    return {"items": [_item(r) for r in rows], "page": page, "size": size, "total": total,
            "summary": jsonable({"branches": summary["n"], "high": summary["high"], "mid": summary["mid"],
                                 "low": summary["low"], "lostPpltn": summary["lost"], "walkLostPpltn": summary["walk_lost"],
                                 "catchPpltn": summary["catch"]}),
            "reasons": REASONS, "rule": RULE, "walk": _walk_meta(c, run["calc_run_id"]),
            "banks": _bank_list_meta(c), "meta": meta_of(run)}


def detail(c: Connection, place_id: str, calc_run_id: str | None) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    p = {"r": run["calc_run_id"], "y": run["stat_year"], "id": place_id}
    r = c.execute(text(f"SELECT {_COLS} {_FROM} WHERE b.calc_run_id = :r AND b.place_id = :id"), p).mappings().first()
    if not r:
        raise NotFound("BANK_IMPACT_NOT_FOUND", f"은행 지점 {place_id} 의 영향평가가 없습니다(새마을금고·저축은행은 평가 대상 아님).")
    # 대체 창구 — 같은 은행 다음 지점, 다른 은행 지점 3곳, 금융 우체국 3곳 (지점 위치 기준)
    alts = c.execute(text("""
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
        {**p, "asof": run["facility_as_of"]}).mappings().all()
    dist = c.execute(text("""
        SELECT width_bucket(alt_m, ARRAY[1000, 2000, 5000, 10000]::real[]) AS band, count(*) AS oa,
               sum(coalesce(n.tot_ppltn, 0)) AS pop
          FROM mart.oa_bank ob JOIN mart.oa_nearest n ON n.calc_run_id = ob.calc_run_id AND n.oa_cd = ob.oa_cd
         WHERE ob.calc_run_id = :r AND ob.b1 = :id GROUP BY 1 ORDER BY 1"""), p).mappings().all()
    labels = ["1km 안", "1~2km", "2~5km", "5~10km", "10km 밖·없음"]
    bands = {int(d["band"] if d["band"] is not None else 4): d for d in dist}
    return {"item": _item(r),
            "alternatives": [jsonable({"kind": a["kind"], "name": a["name"], "sub": a["sub"], "lat": a["lat"],
                                       "lon": a["lon"], "distM": a["dist_m"]}) for a in alts],
            "altBands": [jsonable({"label": labels[i], "oa": bands[i]["oa"] if i in bands else 0,
                                   "ppltn": bands[i]["pop"] if i in bands else 0}) for i in range(5)],
            "reasons": REASONS, "rule": RULE, "walk": _walk_meta(c, run["calc_run_id"]),
            "banks": _bank_list_meta(c), "meta": meta_of(run)}


def catchment_geojson(c: Connection, place_id: str, calc_run_id: str | None) -> str:
    """이 지점이 가장 가까운 은행 지점인 집계구 — 닫히면 대체 창구까지 거리를 속성으로. 경계는 30m 단순화."""
    run = resolve_calc_run(c, calc_run_id)
    fc = c.execute(text("""
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
    meta = meta_of(run, placeId=place_id, crs="EPSG:4326")
    return '{"meta":' + json.dumps(meta, ensure_ascii=False) + "," + fc.lstrip()[1:]
