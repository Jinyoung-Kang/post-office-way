"""은행 지점 — 지도 레이어와 ① 폐쇄 영향평가 목록(순위·필터)·지점 상세(대체 창구)·이용 주민 지도.

영향 계산은 calc/11_bank_impact.sql 과 walk. 여기서는 읽기만.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from atlas.calc.runs import meta_of, resolve_calc_run
from atlas.core.serial import jsonable
from atlas.domain.errors import Invalid, NotFound
from atlas.domain.params import page_params
from atlas.features.banks import queries as q

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
    w = q.walk_run(c, run_id)
    if not w or w["status"] != "DONE":
        return None
    g = w["graph"] or {}
    return jsonable({"speedMps": w["speed_mps"], "limitM": w["limit_m"], "finishedAt": w["finished_at"],
                     "osmLastModified": g.get("osmLastModified"), "vertices": g.get("vertices")})


def _bank_list_meta(c: Connection) -> dict[str, Any]:
    r = q.last_full_crawl(c)
    return jsonable({"fullCrawlAt": r and r["started_at"], "assumption":
                     "우체국 은행대리업: 보도된 '국내 14개 시중·지방은행 모두'를 은행 전체로 가정(은행별 명단 미확인), "
                     "금융 우체국 전체에서 입출금 가능으로 봄."})


def list_impact(c: Connection, calc_run_id: str | None, sido: str | None, sgg: str | None, grade: str | None,
                sort: str, page: int, size: int) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    if sort not in SORTS:
        raise Invalid(f"sort 는 {', '.join(SORTS)} 중 하나입니다.")
    page, size, offset = page_params(page, size, cap=100)
    p = {"r": run["calc_run_id"], "y": run["stat_year"], "sido": sido, "sgg": sgg, "grade": grade,
         "lim": size, "off": offset}
    summary = q.impact_summary(c, p)
    total, rows = q.impact_page(c, p, SORTS[sort])
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
    r = q.impact_one(c, run, place_id)
    if not r:
        raise NotFound("BANK_IMPACT_NOT_FOUND", f"은행 지점 {place_id} 의 영향평가가 없습니다(새마을금고·저축은행은 평가 대상 아님).")
    alts = q.alternatives(c, run, place_id)
    dist = q.alt_distance_bands(c, run["calc_run_id"], place_id)
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
    fc = q.catchment(c, run, place_id)
    meta = meta_of(run, placeId=place_id, crs="EPSG:4326")
    return '{"meta":' + json.dumps(meta, ensure_ascii=False) + "," + fc.lstrip()[1:]


def places_in_bbox(c: Connection, bbox: str, atm: bool, size: int) -> dict[str, Any]:
    """④ 지도 레이어 — 화면 범위 안 은행·금고 지점(ATM 은 선택)."""
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
    except ValueError as e:
        raise Invalid("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
    if not 1 <= size <= 5000:
        raise Invalid("size 는 1~5000 입니다.")
    rows = q.places_in_bbox(c, x1, y1, x2, y2, atm, size)
    return {"items": [jsonable({"placeId": r["place_id"], "name": r["name"], "category": r["category"], "brand": r["brand"],
                                "kind": r["kind"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"], "lastSeen": r["last_seen"]})
                      for r in rows], "total": len(rows)}
