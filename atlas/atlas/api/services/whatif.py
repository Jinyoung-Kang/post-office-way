"""What-if — 선택한 시설 1~5곳을 제외(문 닫음 가정)했을 때의 최근접 거리 변화 (FR-401~402, ADR-005).

영향 지역 = area_nearest 에서 rank 1 시설이 제외 목록에 있는 지역뿐입니다.
그 지역만 rank 2·3 중 제외되지 않은 시설로 바꾸고, 셋 다 제외되면 KNN 으로 다시 찾습니다.
recompute_all() 은 전체 재계산 기준값으로, 동등성 테스트가 부분 재계산과 비교합니다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api import cache
from atlas.api.common import ApiError, bad_request, jsonable, meta_of, not_found, parse_uuid, resolve_calc_run

CAVEAT = "분석 데모 지표이며 공식 통계가 아닙니다. 직선거리 기준이며 도로 거리와 다릅니다."
TTL_S = 3600

_KNN_EXCLUDING = """
    SELECT a.adm_cd, k.hist_id, round(CAST(k.d AS numeric), 2) AS dist_m
      FROM mart.admin_area a
      LEFT JOIN LATERAL (
            SELECT t.hist_id, t.d FROM (
                SELECT h.hist_id, ST_Distance(h.geom_5179, a.rep_point_5179) AS d
                  FROM mart.post_facility_hist h
                 WHERE h.fin_available AND NOT h.is_center
                   AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
                   AND NOT (h.hist_id = ANY(CAST(:ids AS bigint[])))
                 ORDER BY h.geom_5179 <-> a.rep_point_5179 LIMIT 2) t   -- 인덱스 KNN 후 동률 정리
             ORDER BY t.d, t.hist_id LIMIT 1) k ON true
     WHERE a.stat_year = :y AND {where}
"""


def _level_for(run: dict[str, Any], level: int | None) -> int:
    levels = [int(x) for x in run["params"].get("levels", [2])]
    lvl = level or max(levels)
    if lvl not in levels:
        raise bad_request(f"level {lvl} 은 이 calc_run 에서 계산되지 않았습니다 (가능: {levels}).")
    return lvl


def partial_recompute(c: Connection, run: dict[str, Any], level: int, ids: list[int]) -> list[dict[str, Any]]:
    """영향 지역만 재계산 → [{adm_cd, dist_before_m, dist_after_m, new_hist_id}]"""
    rid = run["calc_run_id"]
    affected = c.execute(text("""
        SELECT n.adm_cd, n.dist_m FROM mart.area_nearest n
          JOIN mart.admin_area a ON a.adm_cd = n.adm_cd AND a.stat_year = :y
         WHERE n.calc_run_id = :run AND n.rank = 1 AND n.hist_id = ANY(CAST(:ids AS bigint[])) AND a.level = :lvl"""),
        {"y": run["stat_year"], "run": rid, "ids": ids, "lvl": level}).all()
    if not affected:
        return []
    before = {r[0]: r[1] for r in affected}
    cds = list(before)
    after: dict[str, tuple[int | None, Any]] = {}
    for cd, hid, dist in c.execute(text("""
            SELECT DISTINCT ON (adm_cd) adm_cd, hist_id, dist_m FROM mart.area_nearest
             WHERE calc_run_id = :run AND adm_cd = ANY(CAST(:cds AS text[]))
               AND NOT (hist_id = ANY(CAST(:ids AS bigint[])))
             ORDER BY adm_cd, rank"""), {"run": rid, "cds": cds, "ids": ids}):
        after[cd] = (hid, dist)
    missing = [cd for cd in cds if cd not in after]
    if missing:  # 상위 3개가 모두 제외된 지역 → KNN 재탐색
        for cd, hid, dist in c.execute(text(_KNN_EXCLUDING.format(where="a.adm_cd = ANY(CAST(:cds AS text[]))")),
                                       {"asof": run["facility_as_of"], "ids": ids, "y": run["stat_year"],
                                        "cds": missing}):
            after[cd] = (hid, dist)
    return [{"adm_cd": cd, "dist_before_m": before[cd], "dist_after_m": after.get(cd, (None, None))[1],
             "new_hist_id": after.get(cd, (None, None))[0]} for cd in sorted(cds)]


def recompute_all(c: Connection, run: dict[str, Any], level: int, ids: list[int]) -> dict[str, tuple[Any, Any]]:
    """전체 재계산(기준값) — 레벨의 모든 지역에 대해 제외 후 최근접을 KNN 으로 새로 구함."""
    rows = c.execute(text(_KNN_EXCLUDING.format(where="a.level = :lvl")),
                     {"asof": run["facility_as_of"], "ids": ids, "y": run["stat_year"], "lvl": level}).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _key(run_id: Any, level: int, ids: list[int]) -> str:
    return f"whatif:{run_id}:{level}:{hashlib.sha1(','.join(map(str, ids)).encode()).hexdigest()[:16]}"


def run_whatif(c: Connection, calc_run_id: str | None, remove_ids: list[int], level: int | None) -> dict[str, Any]:
    ids = sorted({int(x) for x in remove_ids})
    if not 1 <= len(ids) <= 5:
        raise bad_request("removeHistIds 는 1~5개여야 합니다.")
    run = resolve_calc_run(c, calc_run_id, require_done=False)
    if run["status"] != "DONE":
        raise ApiError(409, "CALC_RUN_NOT_DONE", f"calcRunId {run['calc_run_id']} 상태가 {run['status']} 입니다.")
    lvl = _level_for(run, level)
    key = _key(run["calc_run_id"], lvl, ids)
    if hit := cache.get(key):
        return json.loads(hit)

    facs = c.execute(text("""
        SELECT hist_id, name, fin_available, ST_Y(geom) AS lat, ST_X(geom) AS lon, addr FROM mart.post_facility_hist
         WHERE hist_id = ANY(CAST(:ids AS bigint[]))
           AND valid_from <= :asof AND (valid_to IS NULL OR valid_to > :asof)"""),
        {"ids": ids, "asof": run["facility_as_of"]}).mappings().all()
    if len(facs) != len(ids):
        missing = sorted(set(ids) - {f["hist_id"] for f in facs})
        raise not_found("FACILITY_NOT_FOUND", f"계산 시점에 유효한 시설이 아닙니다: {missing}")

    existing = c.execute(text("""SELECT scenario_id FROM mart.whatif_scenario
                                 WHERE calc_run_id = :run AND level = :lvl AND removed_hist_ids = CAST(:ids AS bigint[])"""),
                         {"run": run["calc_run_id"], "lvl": lvl, "ids": ids}).scalar()
    if existing:
        out = get_scenario(c, str(existing))
    else:
        results = partial_recompute(c, run, lvl, ids)
        cds = [r["adm_cd"] for r in results]
        pops = {r[0]: r[1] for r in c.execute(text("""
            SELECT adm_cd, tot_ppltn FROM mart.area_population WHERE stat_year = :y AND adm_cd = ANY(CAST(:cds AS text[]))"""),
            {"y": run["stat_year"], "cds": cds})}
        aged = {r[0]: r[1] for r in c.execute(text("""
            SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop WHERE stat_year = :y AND adm_cd = ANY(CAST(:cds AS text[]))"""),
            {"y": run["stat_year"], "cds": cds})}
        bank = {r[0]: float(r[1]) for r in c.execute(text("""
            SELECT adm_cd, value FROM mart.access_metric WHERE calc_run_id = :run AND metric_code = 'NEAREST_BANK_DIST_M'
               AND adm_cd = ANY(CAST(:cds AS text[]))"""), {"run": run["calc_run_id"], "cds": cds})}
        far_m = float(run["params"].get("farKm", 2)) * 1000
        summary = _summary(results, pops, aged)
        summary.update(_fin_access_loss(results, pops, bank, far_m))
        summary.update(_oa_impact(c, run, ids, far_m))
        sid = c.execute(text("""INSERT INTO mart.whatif_scenario (calc_run_id, level, removed_hist_ids, status, summary)
                                VALUES (:run, :lvl, CAST(:ids AS bigint[]), 'DONE', CAST(:s AS jsonb))
                                RETURNING scenario_id"""),
                        {"run": run["calc_run_id"], "lvl": lvl, "ids": ids, "s": json.dumps(jsonable(summary))}).scalar_one()
        for r in results:
            c.execute(text("""INSERT INTO mart.whatif_result (scenario_id, adm_cd, affected_ppltn, affected_aged65,
                                     dist_before_m, dist_after_m, new_nearest_hist_id, nearest_bank_m)
                              VALUES (:sid, :cd, :p, :g, :b, :a, :h, :bk)"""),
                      {"sid": sid, "cd": r["adm_cd"], "p": pops.get(r["adm_cd"]), "g": aged.get(r["adm_cd"]),
                       "b": r["dist_before_m"], "a": r["dist_after_m"], "h": r["new_hist_id"],
                       "bk": bank.get(r["adm_cd"])})
        out = get_scenario(c, str(sid))
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=TTL_S)
    return out


def _summary(results: list[dict[str, Any]], pops: dict[str, Any], aged: dict[str, Any] | None = None) -> dict[str, Any]:
    aged = aged or {}
    n = len(results)
    before = [float(r["dist_before_m"]) for r in results if r["dist_before_m"] is not None]
    after = [float(r["dist_after_m"]) for r in results if r["dist_after_m"] is not None]
    inc = [float(r["dist_after_m"]) - float(r["dist_before_m"]) for r in results
           if r["dist_after_m"] is not None and r["dist_before_m"] is not None]
    return {
        "affectedAreas": n,
        "affectedPpltn": sum(int(pops.get(r["adm_cd"]) or 0) for r in results),
        # KOSIS 미적재면 None (0 과 구분)
        "affectedAged65": (sum(int(aged.get(r["adm_cd"]) or 0) for r in results) if aged else None),
        "avgDistBeforeM": round(sum(before) / len(before), 1) if before else None,
        "avgDistAfterM": round(sum(after) / len(after), 1) if after else None,
        "maxIncreaseM": round(max(inc), 1) if inc else None,
        "areasWithoutFacility": sum(1 for r in results if r["dist_after_m"] is None),
    }


def _fin_access_loss(results: list[dict[str, Any]], pops: dict[str, Any], bank: dict[str, float],
                     far_m: float) -> dict[str, Any]:
    """④ 문을 닫아 '금융 창구가 2km 안에 하나도 없게 되는' 인구 — 은행 지점 자료가 있을 때만."""
    if not bank:
        return {"lostFinAccessPpltn": None}
    lost = 0
    for r in results:
        b, a, bk = r["dist_before_m"], r["dist_after_m"], bank.get(r["adm_cd"], 1e12)
        if b is not None and float(b) <= far_m and (a is None or float(a) > far_m) and bk > far_m:
            lost += int(pops.get(r["adm_cd"]) or 0)
    return {"lostFinAccessPpltn": lost}


def _oa_impact(c: Connection, run: dict[str, Any], ids: list[int], far_m: float) -> dict[str, Any]:
    """① 집계구 단위 — 최근접이 바뀌는 인구와 새로 far_m 밖이 되는 인구(읍면동 대표점 1개보다 정확)."""
    # 계산 통계(oaCount)로 판단 — 'LIMIT 1' 존재 확인은 일반 계획이 계산 여러 개가 쌓인 표를 순차 탐색해 약 100ms (벤치마크)
    has = c.execute(text("SELECT coalesce(CAST(stats->>'oaCount' AS int), 0) > 0 FROM mart.calc_run WHERE calc_run_id = :r"),
                    {"r": run["calc_run_id"]}).scalar()
    if not has:
        return {"oaAffectedPpltn": None, "oaNewlyFarPpltn": None, "lifeHubLostPpltn": None}
    rows = c.execute(text("""
        SELECT n.tot_ppltn, n.dist_m, k.d, n.bank_m, n.pharmacy_m, n.clinic_m
          FROM mart.oa_nearest n
          JOIN mart.oa_area o ON o.oa_cd = n.oa_cd AND o.stat_year = :y
          LEFT JOIN LATERAL (
                SELECT ST_Distance(h.geom_5179, o.rep_point_5179) AS d FROM mart.post_facility_hist h
                 WHERE h.fin_available AND NOT h.is_center
                   AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
                   AND NOT (h.hist_id = ANY(CAST(:ids AS bigint[])))
                 ORDER BY h.geom_5179 <-> o.rep_point_5179 LIMIT 1) k ON true
         WHERE n.calc_run_id = :run AND n.hist_id = ANY(CAST(:ids AS bigint[]))"""),
        {"y": run["stat_year"], "asof": run["facility_as_of"], "ids": ids, "run": run["calc_run_id"]}).all()
    def newly_far(b, a) -> bool:
        return b is not None and float(b) <= far_m and (a is None or float(a) > far_m)

    def none_near(*ds) -> bool:
        return all(d is not None and float(d) > far_m for d in ds)

    # ⑦ 새로 2km 밖이 되면서 은행 지점·약국·의원도 2km 안에 없는 인구 — 문을 닫아 생활 거점을 모두 잃음
    has_life = any(r[4] is not None and r[5] is not None for r in rows)
    return {"oaAffectedPpltn": sum(int(r[0] or 0) for r in rows),
            "oaNewlyFarPpltn": sum(int(r[0] or 0) for r in rows if newly_far(r[1], r[2])),
            "lifeHubLostPpltn": (sum(int(r[0] or 0) for r in rows
                                     if newly_far(r[1], r[2]) and none_near(r[3], r[4], r[5])) if has_life else None)}


def get_scenario(c: Connection, scenario_id: str) -> dict[str, Any]:
    sid = parse_uuid(scenario_id, "scenarioId")
    s = c.execute(text("""SELECT s.*, r.stat_year, r.facility_as_of FROM mart.whatif_scenario s
                          JOIN mart.calc_run r ON r.calc_run_id = s.calc_run_id WHERE s.scenario_id = :id"""),
                  {"id": sid}).mappings().first()
    if not s:
        raise not_found("SCENARIO_NOT_FOUND", f"scenarioId {sid} 가 없습니다.")
    rows = c.execute(text("""
        SELECT w.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm, w.affected_ppltn, w.affected_aged65,
               w.dist_before_m, w.dist_after_m, w.nearest_bank_m,
               w.new_nearest_hist_id, h.name AS new_nearest_name, ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon
          FROM mart.whatif_result w
          JOIN mart.admin_area a ON a.adm_cd = w.adm_cd AND a.stat_year = :y
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
          LEFT JOIN mart.post_facility_hist h ON h.hist_id = w.new_nearest_hist_id
         WHERE w.scenario_id = :id
         ORDER BY (w.dist_after_m - w.dist_before_m) DESC NULLS FIRST"""),
        {"id": sid, "y": s["stat_year"]}).mappings().all()
    removed = c.execute(text("""SELECT hist_id, name, addr, ST_Y(geom) AS lat, ST_X(geom) AS lon
                                FROM mart.post_facility_hist WHERE hist_id = ANY(CAST(:ids AS bigint[]))
                                ORDER BY hist_id"""), {"ids": list(s["removed_hist_ids"])}).mappings().all()
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
    if not c.execute(text("SELECT 1 FROM mart.whatif_scenario WHERE scenario_id = :id"), {"id": sid}).first():
        raise not_found("SCENARIO_NOT_FOUND", f"scenarioId {sid} 가 없습니다.")
    fc = c.execute(text("""
        SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                 'type', 'Feature', 'id', a.adm_cd,
                 'properties', json_build_object('admCd', a.adm_cd, 'admNm', a.adm_nm,
                     'distBeforeM', w.dist_before_m, 'distAfterM', w.dist_after_m,
                     'increaseM', w.dist_after_m - w.dist_before_m, 'affectedPpltn', w.affected_ppltn,
                     'affectedAged65', w.affected_aged65),
                 'geometry', CAST(ST_AsGeoJSON(coalesce(a.geom_simple, a.geom), 5) AS json))), CAST('[]' AS json)))
          FROM mart.whatif_result w
          JOIN mart.whatif_scenario s ON s.scenario_id = w.scenario_id
          JOIN mart.calc_run r ON r.calc_run_id = s.calc_run_id
          JOIN mart.admin_area a ON a.adm_cd = w.adm_cd AND a.stat_year = r.stat_year
         WHERE w.scenario_id = :id"""), {"id": sid}).scalar_one()
    return fc if isinstance(fc, dict) else json.loads(fc)
