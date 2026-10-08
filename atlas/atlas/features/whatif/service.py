"""What-if — 선택한 시설 1~5곳을 제외(문 닫음 가정)했을 때의 최근접 거리 변화 (FR-401~402, ADR-005).

영향 지역 = area_nearest 에서 rank 1 시설이 제외 목록에 있는 지역뿐입니다.
그 지역만 rank 2·3 중 제외되지 않은 시설로 바꾸고, 셋 다 제외되면 KNN 으로 다시 찾습니다.
recompute_all() 은 전체 재계산 기준값으로, 동등성 테스트가 부분 재계산과 비교합니다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.engine import Connection

from atlas.calc.runs import meta_of, resolve_calc_run
from atlas.core import cache
from atlas.core.serial import jsonable
from atlas.domain.errors import Conflict, Invalid, NotFound
from atlas.domain.params import far_meters, parse_uuid, pick_level
from atlas.domain.whatif import fin_access_loss, oa_impact, summarize
from atlas.features.whatif import queries as q

CAVEAT = "분석 데모 지표이며 공식 통계가 아닙니다. 직선거리 기준이며 도로 거리와 다릅니다."
TTL_S = 3600


def partial_recompute(c: Connection, run: dict[str, Any], level: int, ids: list[int]) -> list[dict[str, Any]]:
    """영향 지역만 재계산 → [{adm_cd, dist_before_m, dist_after_m, new_hist_id}]"""
    before = q.nearest_removed(c, run, level, ids)
    if not before:
        return []
    cds = list(before)
    after = q.next_nearest(c, run["calc_run_id"], cds, ids)
    missing = [cd for cd in cds if cd not in after]
    if missing:  # 상위 3개가 모두 제외된 지역 → KNN 재탐색
        for cd, hid, dist in q.knn_excluding(c, run, ids, cds=missing):
            after[cd] = (hid, dist)
    return [{"adm_cd": cd, "dist_before_m": before[cd], "dist_after_m": after.get(cd, (None, None))[1],
             "new_hist_id": after.get(cd, (None, None))[0]} for cd in sorted(cds)]


def recompute_all(c: Connection, run: dict[str, Any], level: int, ids: list[int]) -> dict[str, tuple[Any, Any]]:
    """전체 재계산(기준값) — 레벨의 모든 지역에 대해 제외 후 최근접을 KNN 으로 새로 구함."""
    return {r[0]: (r[1], r[2]) for r in q.knn_excluding(c, run, ids, level=level)}


def _key(run_id: Any, level: int, ids: list[int]) -> str:
    return f"whatif:{run_id}:{level}:{hashlib.sha1(','.join(map(str, ids)).encode()).hexdigest()[:16]}"


def run_whatif(c: Connection, calc_run_id: str | None, remove_ids: list[int], level: int | None) -> dict[str, Any]:
    ids = sorted({int(x) for x in remove_ids})
    if not 1 <= len(ids) <= 5:
        raise Invalid("removeHistIds 는 1~5개여야 합니다.")
    run = resolve_calc_run(c, calc_run_id, require_done=False)
    if run["status"] != "DONE":
        raise Conflict("CALC_RUN_NOT_DONE", f"calcRunId {run['calc_run_id']} 상태가 {run['status']} 입니다.")
    lvl = pick_level(run["params"], level)
    key = _key(run["calc_run_id"], lvl, ids)
    if hit := cache.get(key):
        return json.loads(hit)

    facs = q.facilities_at(c, ids, run["facility_as_of"])
    if len(facs) != len(ids):
        missing = sorted(set(ids) - {f["hist_id"] for f in facs})
        raise NotFound("FACILITY_NOT_FOUND", f"계산 시점에 유효한 시설이 아닙니다: {missing}")

    existing = q.scenario_id_for(c, run["calc_run_id"], lvl, ids)
    if existing:
        out = get_scenario(c, str(existing))
    else:
        results = partial_recompute(c, run, lvl, ids)
        pops, aged, bank = q.area_inputs(c, run, [r["adm_cd"] for r in results])
        far_m = far_meters(run["params"])
        summary = summarize(results, pops, aged)
        summary.update(fin_access_loss(results, pops, bank, far_m))
        summary.update(_oa_impact(c, run, ids, far_m))
        sid = q.insert_scenario(c, run["calc_run_id"], lvl, ids, jsonable(summary))
        if sid is None:
            # 같은 시나리오를 다른 요청(동시 요청·더블클릭)이 먼저 저장함 — 그것을 돌려줌 (예전에는 고유 제약 위반으로 500, R3)
            existing = q.scenario_id_for(c, run["calc_run_id"], lvl, ids)
            return get_scenario(c, str(existing))
        q.insert_results(c, sid, results, pops, aged, bank)
        out = get_scenario(c, str(sid))
    return out


def remember(out: dict[str, Any]) -> None:
    """결과 캐시 — 저장 트랜잭션이 커밋된 '뒤에' 부르는 쪽(라우터)이 부름. 커밋되지 않은 시나리오 id 를 1시간 동안 돌려주지 않게
    (SQLAlchemy 의 commit 이벤트는 DB COMMIT 직전에 불려, 이벤트로 캐시하면 COMMIT 이 실패해도 남았음)."""
    key = _key(out["meta"]["calcRunId"], out["level"], sorted(r["histId"] for r in out["removed"]))
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=TTL_S)


def _oa_impact(c: Connection, run: dict[str, Any], ids: list[int], far_m: float) -> dict[str, Any]:
    """① 집계구 단위 영향 — 집계구 결과가 없는 계산이면 모두 None."""
    if not q.has_oa(c, run["calc_run_id"]):
        return {"oaAffectedPpltn": None, "oaNewlyFarPpltn": None, "lifeHubLostPpltn": None}
    return oa_impact(q.oa_rows(c, run, ids), far_m)


def get_scenario(c: Connection, scenario_id: str) -> dict[str, Any]:
    sid = parse_uuid(scenario_id, "scenarioId")
    s = q.scenario(c, sid)
    if not s:
        raise NotFound("SCENARIO_NOT_FOUND", f"scenarioId {sid} 가 없습니다.")
    rows = q.scenario_areas(c, sid, s["stat_year"])
    removed = q.removed_facilities(c, list(s["removed_hist_ids"]))
    run = {"calc_run_id": s["calc_run_id"], "stat_year": s["stat_year"], "facility_as_of": s["facility_as_of"]}
    return jsonable({
        "scenarioId": s["scenario_id"], "level": s["level"], "createdAt": s["created_at"],
        "removed": [{"histId": r["hist_id"], "name": r["name"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"]}
                    for r in removed],
        "summary": s["summary"],
        "areas": [{"admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentNm": r["parent_nm"],
                   "affectedPpltn": r["affected_ppltn"], "affectedAged65": r["affected_aged65"],
                   "nearestBankM": r["nearest_bank_m"],
                   "distBeforeM": r["dist_before_m"],
                   "distAfterM": r["dist_after_m"], "newNearestHistId": r["new_nearest_hist_id"],
                   "newNearestName": r["new_nearest_name"], "lat": r["lat"], "lon": r["lon"]} for r in rows],
        "caveat": CAVEAT,
        "meta": meta_of(run),
    })


def scenario_geojson(c: Connection, scenario_id: str) -> dict[str, Any]:
    sid = parse_uuid(scenario_id, "scenarioId")
    if not q.scenario_exists(c, sid):
        raise NotFound("SCENARIO_NOT_FOUND", f"scenarioId {sid} 가 없습니다.")
    fc = q.scenario_geojson(c, sid)
    return fc if isinstance(fc, dict) else json.loads(fc)
