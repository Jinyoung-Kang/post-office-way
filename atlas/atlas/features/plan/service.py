"""⑤ 배치 제안 — What-if 를 뒤집어 '어디를 닫으면 영향이 가장 적은가 / 어디에 열면 효과가 가장 큰가'를 계산.

- close: 범위(시도·시군구) 안 금융 가능 우체국 중 k곳(≤7)을 닫는다면, 가중 인구 × 늘어나는 거리의 합(명·km)이
  가장 작게 늘어나는 조합을 탐욕법으로 고릅니다. 수요 지점마다 직선 상위 8곳을 미리 구해 두므로 k ≤ 7 이면
  재탐색 없이 정확합니다(8곳 모두 닫힐 수 없음). 수요 지점은 집계구(평균 약 500명)가 있으면 집계구,
  없으면 읍면동 대표점 — 읍면동 대표점만으로는 도시 우체국 대부분이 '어느 지점의 최근접도 아님'이 되어 영향 0 으로 보임.
- open: 범위 안 읍면동 대표점을 후보지로, 새 우체국을 k곳(≤7) 연다면 가중 인구 × 줄어드는 거리의 합이
  가장 큰 곳부터 고릅니다(p-median 탐욕 근사). 후보지 15km 안 지역만 효과를 셉니다.
가중치: 65세 이상(KOSIS, 없으면 전체 인구로 대체) 또는 전체 인구(SGIS). 직선거리 기준 — 공식 판단 근거 아님.
인구 추세(행안부 인구이동 12개월 순유출)는 가중치에 넣지 않고 결과마다 경고 열로만 붙입니다 (ADR-028).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.engine import Connection

from atlas.calc.runs import meta_of, resolve_calc_run
from atlas.core import cache
from atlas.core.serial import jsonable
from atlas.domain.errors import Invalid, NotFound
from atlas.domain.params import far_meters, parse_region_code, pick_level
from atlas.domain.placement import Area, greedy_close, greedy_open, single_impacts
from atlas.features.plan import queries as q

TOP_N = 8
MAX_K = 7
OPEN_RADIUS_M = 15000
CAVEAT = "직선거리·지역 대표점 기준의 탐욕 근사이며 공식 판단 근거가 아닙니다. 실제 결정에는 도로 접근성·수요·비용을 함께 봐야 합니다."


def _validate(scope: str, k: int, weight: str) -> None:
    parse_region_code(scope, (2, 5), "scope 는 시도 2자리 또는 시군구 5자리 코드입니다.")
    if not 1 <= k <= MAX_K:
        raise Invalid(f"k 는 1~{MAX_K} 입니다.")
    if weight not in ("aged65", "pop"):
        raise Invalid("weight 는 aged65 또는 pop 입니다.")


def _weights(c: Connection, y: int, cds: list[str], weight: str) -> tuple[dict[str, float], str]:
    """지역 가중치 — 65세 이상(KOSIS)이 없으면 전체 인구로 대체."""
    pop = q.area_pop(c, y, cds)
    if weight == "aged65":
        aged = q.area_aged65(c, y, cds)
        if aged:
            return {cd: aged.get(cd, 0.0) for cd in cds}, "aged65"
    return {cd: pop.get(cd, 0.0) for cd in cds}, "pop"


def _oa_weights(c: Connection, y: int, oas: list[str], weight: str) -> tuple[dict[str, float], str]:
    """집계구 가중치 — 인구는 집계구 인구, 65세 이상은 집계구 인구 × 상위 읍면동 고령인구 비율(KOSIS)."""
    rows = q.oa_pop_aged_ratio(c, y, oas)
    if weight == "aged65" and any(r[2] is not None for r in rows):
        return {cd: float(p or 0) * float(ratio or 0) / 100 for cd, p, ratio in rows}, "aged65"
    return {cd: float(p or 0) for cd, p, _ in rows}, "pop"


ALGO_VERSION = "5"   # 알고리즘·응답 형식이 바뀌면 올려서 이전 캐시를 무효화 (5: 순유출 경고 열 netOutPer1k·netOutPct)


def _trend(v: tuple[Any, Any] | None) -> dict[str, Any]:
    """그 시군구의 12개월 순유출(천 명당)과 백분위(클수록 유출이 많은 쪽) — 인구 추세 자료가 없으면 null."""
    return {"netOutPer1k": v[0] if v else None, "netOutPct": v[1] if v else None}


def _key(kind: str, run_id: Any, **kw: Any) -> str:
    return f"plan:v{ALGO_VERSION}:{kind}:{run_id}:" + hashlib.sha1(json.dumps(kw, sort_keys=True).encode()).hexdigest()[:16]


def plan_close(c: Connection, scope: str, k: int, weight: str, level: int | None = None,
               calc_run_id: str | None = None) -> dict[str, Any]:
    _validate(scope, k, weight)
    run = resolve_calc_run(c, calc_run_id)
    lvl, y, far_m = pick_level(run["params"], level), run["stat_year"], far_meters(run["params"])
    key = _key("close", run["calc_run_id"], scope=scope, k=k, weight=weight, level=lvl)
    if hit := cache.get(key):
        return json.loads(hit)
    facs = q.candidates(c, run, scope)
    if not facs:
        raise NotFound("NO_CANDIDATE", f"범위 {scope} 안에 금융 가능 우체국이 없습니다.")
    # 수요 지점: 집계구(평균 약 500명)가 있으면 집계구, 없으면 지역 대표점
    use_oa = q.has_oa_in(c, y, scope)
    rows = q.demand_top_n(c, run, lvl, scope, list(facs), use_oa, TOP_N)
    cands: dict[str, list[tuple[int, float]]] = {}
    grp: dict[str, str] = {}
    for cd, g, h, d in rows:
        cands.setdefault(cd, []).append((h, float(d)))
        grp[cd] = g
    if use_oa:
        w, used = _oa_weights(c, y, list(cands), weight)
    else:
        w, used = _weights(c, y, list(cands), weight)
    areas = [Area(cd, w.get(cd, 0.0), lst) for cd, lst in cands.items()]
    steps = greedy_close(areas, sorted(facs), k, far_m)
    # 모든 후보의 '혼자 닫을 때' 영향 (표용) — 한 번 훑어서 계산
    si = single_impacts(areas, far_m)
    zero = {"addedCost": 0.0, "newlyFar": 0.0, "areasAffected": 0}
    singles = sorted(({**facs[h], "histId": h, **si.get(h, zero)} for h in facs),
                     key=lambda r: (r["addedCost"], r["histId"]))
    # ⑦ 닫으면 생활 거점을 모두 잃는 인구(우체국별, 최신 계산) — 제안 목록에 경고로 함께 표시
    hub = q.sole_hub(c, run["calc_run_id"], sorted(facs))
    trend = q.net_out_of_facilities(c, run["calc_run_id"], y, sorted(facs))    # 시설이 있는 시군구의 순유출 — 경고만
    removed: set[int] = set()
    out_steps = []
    for st in steps:
        removed.add(st["histId"])
        out_steps.append({**facs[st["histId"]], **st, "addedKmPpl": round(st["addedCost"] / 1000, 1),
                          "newlyFar": round(st["newlyFar"]), "soleHubPpltn": hub.get(st["histId"]),
                          **_trend(trend.get(st["histId"]))})
    # 거리가 늘어나는 수요 지점을 읍면동(집계구면 상위 읍면동)으로 묶어 가중 평균 거리로 표시
    agg: dict[str, list[float]] = {}
    for a in areas:
        b, n = a.dist(set()), a.dist(removed)
        if b is not None and n is not None and n > b:
            g = agg.setdefault(grp[a.cd], [0.0, 0.0, 0.0, 0.0])   # 가중치, Σw·전, Σw·후, 지점 수
            ww = max(a.w, 1e-9)
            g[0] += a.w; g[1] += ww * b; g[2] += ww * n; g[3] += ww
    names = q.area_names(c, y, list(agg))
    affected = sorted(({"admCd": g, "admNm": names.get(g), "weight": round(v[0]), "distBeforeM": round(v[1] / v[3], 1),
                        "distAfterM": round(v[2] / v[3], 1)} for g, v in agg.items()),
                      key=lambda r: -(r["distAfterM"] - r["distBeforeM"]) * max(r["weight"], 1))
    out = jsonable({
        "mode": "close", "scope": scope, "scopeName": q.scope_name(c, y, scope), "k": k, "level": lvl,
        "demandUnit": "oa" if use_oa else "area", "demandPoints": len(areas),
        "weight": used, "weightFallback": used != weight, "farM": far_m,
        "candidateCount": len(facs), "steps": out_steps,
        "totalAddedKmPpl": round(sum(s["addedCost"] for s in steps) / 1000, 1),
        "totalNewlyFar": round(sum(s["newlyFar"] for s in steps)),
        "affectedAreas": affected[:50],
        "leastImpact": [{"histId": r["histId"], "name": r["name"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"],
                         "addedKmPpl": round(r["addedCost"] / 1000, 1), "newlyFar": round(r["newlyFar"]),
                         "areasAffected": r["areasAffected"], "soleHubPpltn": hub.get(r["histId"]),
                         **_trend(trend.get(r["histId"]))} for r in singles[:15]],
        "mostCritical": [{"histId": r["histId"], "name": r["name"], "addr": r["addr"],
                          "addedKmPpl": round(r["addedCost"] / 1000, 1), "newlyFar": round(r["newlyFar"]),
                          "areasAffected": r["areasAffected"], "soleHubPpltn": hub.get(r["histId"]),
                          **_trend(trend.get(r["histId"]))} for r in singles[::-1][:10]],
        "caveat": CAVEAT, "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=3600)
    return out


def plan_open(c: Connection, scope: str, k: int, weight: str, level: int | None = None,
              calc_run_id: str | None = None) -> dict[str, Any]:
    _validate(scope, k, weight)
    run = resolve_calc_run(c, calc_run_id)
    lvl, y, far_m = pick_level(run["params"], level), run["stat_year"], far_meters(run["params"])
    key = _key("open", run["calc_run_id"], scope=scope, k=k, weight=weight, level=lvl)
    if hit := cache.get(key):
        return json.loads(hit)
    cur = q.current_nearest(c, run["calc_run_id"], y, lvl, scope)
    if not cur:
        raise NotFound("NO_AREA", f"범위 {scope} 에 계산된 지역이 없습니다.")
    near: dict[str, list[tuple[str, float]]] = {}
    for s, a, d in q.sites_within(c, y, lvl, scope, OPEN_RADIUS_M):
        if a in cur:
            near.setdefault(s, []).append((a, float(d)))
    w, used = _weights(c, y, list(cur), weight)
    steps = greedy_open(cur, w, near, k, far_m)
    names = q.area_names(c, y, list(cur))
    pts = q.rep_points(c, y, [s["siteCd"] for s in steps])
    trend = q.net_out_of_areas(c, run["calc_run_id"], [s["siteCd"] for s in steps])
    after = dict(cur)
    for st in steps:
        for a, d in near[st["siteCd"]]:
            after[a] = min(after[a], d)
    improved = sorted(({"admCd": a, "admNm": names.get(a), "weight": round(w.get(a, 0)), "distBeforeM": round(cur[a], 1),
                        "distAfterM": round(after[a], 1)} for a in cur if after[a] < cur[a]),
                      key=lambda r: -(r["distBeforeM"] - r["distAfterM"]) * max(r["weight"], 1))
    out = jsonable({
        "mode": "open", "scope": scope, "scopeName": q.scope_name(c, y, scope), "k": k, "level": lvl,
        "weight": used, "weightFallback": used != weight, "farM": far_m, "candidateCount": len(near),
        "steps": [{**st, "siteNm": names.get(st["siteCd"]), "lat": pts.get(st["siteCd"], (None, None))[0],
                   "lon": pts.get(st["siteCd"], (None, None))[1], "gainKmPpl": round(st["gain"] / 1000, 1),
                   "newlyNear": round(st["newlyNear"]), **_trend(trend.get(st["siteCd"]))} for st in steps],
        "totalGainKmPpl": round(sum(s["gain"] for s in steps) / 1000, 1),
        "totalNewlyNear": round(sum(s["newlyNear"] for s in steps)),
        "improvedAreas": improved[:50],
        "caveat": CAVEAT, "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=3600)
    return out
