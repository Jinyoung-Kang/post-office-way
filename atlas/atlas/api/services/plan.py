"""⑤ 배치 제안 — What-if 를 뒤집어 '어디를 닫으면 영향이 가장 적은가 / 어디에 열면 효과가 가장 큰가'를 계산.

- close: 범위(시도·시군구) 안 금융 가능 우체국 중 k곳(≤7)을 닫는다면, 가중 인구 × 늘어나는 거리의 합(명·km)이
  가장 작게 늘어나는 조합을 탐욕법으로 고릅니다. 수요 지점마다 직선 상위 8곳을 미리 구해 두므로 k ≤ 7 이면
  재탐색 없이 정확합니다(8곳 모두 닫힐 수 없음). 수요 지점은 집계구(평균 약 500명)가 있으면 집계구,
  없으면 읍면동 대표점 — 읍면동 대표점만으로는 도시 우체국 대부분이 '어느 지점의 최근접도 아님'이 되어 영향 0 으로 보임.
- open: 범위 안 읍면동 대표점을 후보지로, 새 우체국을 k곳(≤7) 연다면 가중 인구 × 줄어드는 거리의 합이
  가장 큰 곳부터 고릅니다(p-median 탐욕 근사). 후보지 15km 안 지역만 효과를 셉니다.
가중치: 65세 이상(KOSIS, 없으면 전체 인구로 대체) 또는 전체 인구(SGIS). 직선거리 기준 — 공식 판단 근거 아님.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api import cache
from atlas.api.common import bad_request, jsonable, meta_of, not_found, resolve_calc_run

TOP_N = 8
MAX_K = 7
OPEN_RADIUS_M = 15000
CAVEAT = "직선거리·지역 대표점 기준의 탐욕 근사이며 공식 판단 근거가 아닙니다. 실제 결정에는 도로 접근성·수요·비용을 함께 봐야 합니다."


# ---------------------------------------------------------------------------------------- 순수 알고리즘
@dataclass
class Area:
    cd: str
    w: float                                   # 가중 인구
    cands: list[tuple[int, float]] = field(default_factory=list)   # 거리순 (시설, 거리 m)

    def dist(self, removed: set[int]) -> float | None:
        for h, d in self.cands:
            if h not in removed:
                return d
        return None


def greedy_close(areas: list[Area], candidates: list[int], k: int, far_m: float) -> list[dict[str, Any]]:
    """닫아도 영향이 가장 작은 시설부터 k개. 각 단계의 추가 영향(명·m)과 새로 far_m 밖으로 밀려나는 가중 인구."""
    by_fac: dict[int, list[Area]] = {}
    for a in areas:
        for h, _ in a.cands:
            by_fac.setdefault(h, []).append(a)
    removed: set[int] = set()
    steps = []
    for _ in range(min(k, len(candidates))):
        best = None
        for c in candidates:
            if c in removed:
                continue
            cost, newly_far, touched = 0.0, 0.0, 0
            after = removed | {c}
            for a in by_fac.get(c, []):
                before, now = a.dist(removed), a.dist(after)
                if before is None or now is None or now == before:
                    continue
                cost += a.w * (now - before)
                touched += 1
                if before <= far_m < now:
                    newly_far += a.w
            key = (cost, c)
            if best is None or key < best[0]:
                best = (key, c, cost, newly_far, touched)
        if best is None:
            break
        _, c, cost, newly_far, touched = best
        removed.add(c)
        steps.append({"histId": c, "addedCost": cost, "newlyFar": newly_far, "areasAffected": touched})
    return steps


def single_impacts(areas: list[Area], far_m: float) -> dict[int, dict[str, float]]:
    """각 시설을 '혼자' 닫을 때의 영향 — 그 시설이 1순위인 수요 지점만 2순위로 바뀜. O(지점 수)."""
    out: dict[int, dict[str, float]] = {}
    for a in areas:
        for h, _ in a.cands:
            out.setdefault(h, {"addedCost": 0.0, "newlyFar": 0.0, "areasAffected": 0})
        if len(a.cands) < 2:
            continue
        (h1, d1), (_, d2) = a.cands[0], a.cands[1]
        if d2 > d1:
            o = out[h1]
            o["addedCost"] += a.w * (d2 - d1)
            o["areasAffected"] += 1
            if d1 <= far_m < d2:
                o["newlyFar"] += a.w
    return out


def greedy_open(cur: dict[str, float], w: dict[str, float], near: dict[str, list[tuple[str, float]]],
                k: int, far_m: float) -> list[dict[str, Any]]:
    """새로 열면 효과가 가장 큰 후보지부터 k개. near[s] = [(지역, 후보지까지 거리)]."""
    cur = dict(cur)
    picked: list[str] = []
    steps = []
    for _ in range(k):
        best = None
        for s, lst in near.items():
            if s in picked:
                continue
            gain, newly_near, reached = 0.0, 0.0, 0
            for a, d in lst:
                if d < cur[a]:
                    gain += w[a] * (cur[a] - d)
                    reached += 1
                    if cur[a] > far_m >= d:
                        newly_near += w[a]
            key = (gain, newly_near, s)
            if best is None or key > best[0]:
                best = (key, s, gain, newly_near, reached)
        if best is None or best[2] <= 0:
            break
        _, s, gain, newly_near, reached = best
        picked.append(s)
        for a, d in near[s]:
            cur[a] = min(cur[a], d)
        steps.append({"siteCd": s, "gain": gain, "newlyNear": newly_near, "areasImproved": reached})
    return steps


# ---------------------------------------------------------------------------------------- DB 연결
def _validate(scope: str, k: int, weight: str) -> None:
    if not scope or not scope.isdigit() or len(scope) not in (2, 5):
        raise bad_request("scope 는 시도 2자리 또는 시군구 5자리 코드입니다.")
    if not 1 <= k <= MAX_K:
        raise bad_request(f"k 는 1~{MAX_K} 입니다.")
    if weight not in ("aged65", "pop"):
        raise bad_request("weight 는 aged65 또는 pop 입니다.")


def _weights(c: Connection, y: int, cds: list[str], weight: str) -> tuple[dict[str, float], str]:
    pop = {r[0]: float(r[1] or 0) for r in c.execute(text("""SELECT adm_cd, tot_ppltn FROM mart.area_population
                                                           WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""),
                                                      {"y": y, "c": cds})}
    if weight == "aged65":
        aged = {r[0]: float(r[1] or 0) for r in c.execute(text("""SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop
                                                            WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""),
                                                           {"y": y, "c": cds})}
        if aged:
            return {cd: aged.get(cd, 0.0) for cd in cds}, "aged65"
    return {cd: pop.get(cd, 0.0) for cd in cds}, "pop"


def _oa_weights(c: Connection, y: int, oas: list[str], weight: str) -> tuple[dict[str, float], str]:
    """집계구 가중치 — 인구는 집계구 인구, 65세 이상은 집계구 인구 × 상위 읍면동 고령인구 비율(KOSIS)."""
    rows = c.execute(text("""SELECT o.oa_cd, o.tot_ppltn, r.aged65_ratio FROM mart.oa_area o
                              LEFT JOIN mart.area_resident_pop r ON r.adm_cd = o.emd_cd AND r.stat_year = o.stat_year
                             WHERE o.stat_year = :y AND o.oa_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": oas}).all()
    if weight == "aged65" and any(r[2] is not None for r in rows):
        return {cd: float(p or 0) * float(ratio or 0) / 100 for cd, p, ratio in rows}, "aged65"
    return {cd: float(p or 0) for cd, p, _ in rows}, "pop"


ALGO_VERSION = "4"   # 알고리즘·응답 형식이 바뀌면 올려서 이전 캐시를 무효화


def _key(kind: str, run_id: Any, **kw: Any) -> str:
    return f"plan:v{ALGO_VERSION}:{kind}:{run_id}:" + hashlib.sha1(json.dumps(kw, sort_keys=True).encode()).hexdigest()[:16]


def _level(run: dict[str, Any], level: int | None) -> int:
    levels = [int(x) for x in run["params"].get("levels", [2])]
    lvl = level or max(levels)
    if lvl not in levels:
        raise bad_request(f"level {lvl} 은 이 calc_run 에서 계산되지 않았습니다 (가능: {levels}).")
    return lvl


def plan_close(c: Connection, scope: str, k: int, weight: str, level: int | None = None,
               calc_run_id: str | None = None) -> dict[str, Any]:
    _validate(scope, k, weight)
    run = resolve_calc_run(c, calc_run_id)
    lvl, y, far_m = _level(run, level), run["stat_year"], float(run["params"].get("farKm", 2)) * 1000
    key = _key("close", run["calc_run_id"], scope=scope, k=k, weight=weight, level=lvl)
    if hit := cache.get(key):
        return json.loads(hit)
    snap = "h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof) AND h.fin_available AND NOT h.is_center"
    facs = {r["hist_id"]: dict(r) for r in c.execute(text(f"""
        SELECT h.hist_id, h.name, h.addr, ST_Y(h.geom) AS lat, ST_X(h.geom) AS lon
          FROM mart.post_facility_hist h
          JOIN mart.facility_area_map m ON m.hist_id = h.hist_id AND m.stat_year = :y AND m.level = :mlvl
         WHERE {snap} AND m.adm_cd LIKE :scope || '%'"""),
        {"asof": run["facility_as_of"], "y": y, "scope": scope,
         "mlvl": min(int(x) for x in run["params"].get("levels", [2]))}).mappings()}
    if not facs:
        raise not_found("NO_CANDIDATE", f"범위 {scope} 안에 금융 가능 우체국이 없습니다.")
    use_oa = c.execute(text("""SELECT 1 FROM mart.oa_area WHERE stat_year = :y AND emd_cd LIKE :scope || '%'
                                  AND rep_point_5179 IS NOT NULL AND tot_ppltn > 0 LIMIT 1"""),
                       {"y": y, "scope": scope}).first() is not None
    if use_oa:
        # 집계구: 범위 안 집계구 + 범위 밖이지만 이번 계산에서 1순위가 후보인 집계구
        pts_sql = """SELECT o.oa_cd AS cd, o.emd_cd AS grp, o.rep_point_5179 AS p FROM mart.oa_area o
                      WHERE o.stat_year = :y AND o.rep_point_5179 IS NOT NULL AND o.tot_ppltn > 0
                        AND (o.emd_cd LIKE :scope || '%' OR o.oa_cd IN (
                             SELECT n.oa_cd FROM mart.oa_nearest n WHERE n.calc_run_id = :run
                                AND n.hist_id = ANY(CAST(:ids AS bigint[]))))"""
    else:
        pts_sql = """SELECT a.adm_cd AS cd, a.adm_cd AS grp, a.rep_point_5179 AS p FROM mart.admin_area a
                      WHERE a.stat_year = :y AND a.level = :lvl
                        AND (a.adm_cd LIKE :scope || '%' OR EXISTS (
                             SELECT 1 FROM mart.area_nearest n WHERE n.calc_run_id = :run AND n.adm_cd = a.adm_cd
                                AND n.rank = 1 AND n.hist_id = ANY(CAST(:ids AS bigint[]))))"""
    rows = c.execute(text(f"""
        WITH pts AS ({pts_sql})
        SELECT pts.cd, pts.grp, k.hist_id, k.d
          FROM pts
         CROSS JOIN LATERAL (
                SELECT h.hist_id, ST_Distance(h.geom_5179, pts.p) AS d
                  FROM mart.post_facility_hist h WHERE {snap}
                 ORDER BY h.geom_5179 <-> pts.p LIMIT {TOP_N}) k
         ORDER BY pts.cd, k.d, k.hist_id"""),
        {"y": y, "lvl": lvl, "scope": scope, "run": run["calc_run_id"], "ids": list(facs),
         "asof": run["facility_as_of"]}).all()
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
    hub = {h: s for h, s in c.execute(text("""SELECT hist_id, sole_hub_ppltn FROM mart.facility_hub
                                               WHERE calc_run_id = :r AND hist_id = ANY(CAST(:ids AS bigint[]))"""),
                                      {"r": run["calc_run_id"], "ids": sorted(facs)})}
    removed: set[int] = set()
    out_steps = []
    for st in steps:
        removed.add(st["histId"])
        out_steps.append({**facs[st["histId"]], **st, "addedKmPpl": round(st["addedCost"] / 1000, 1),
                          "newlyFar": round(st["newlyFar"]), "soleHubPpltn": hub.get(st["histId"])})
    # 거리가 늘어나는 수요 지점을 읍면동(집계구면 상위 읍면동)으로 묶어 가중 평균 거리로 표시
    agg: dict[str, list[float]] = {}
    for a in areas:
        b, n = a.dist(set()), a.dist(removed)
        if b is not None and n is not None and n > b:
            g = agg.setdefault(grp[a.cd], [0.0, 0.0, 0.0, 0.0])   # 가중치, Σw·전, Σw·후, 지점 수
            ww = max(a.w, 1e-9)
            g[0] += a.w; g[1] += ww * b; g[2] += ww * n; g[3] += ww
    names = _area_names(c, y, list(agg))
    affected = sorted(({"admCd": g, "admNm": names.get(g), "weight": round(v[0]), "distBeforeM": round(v[1] / v[3], 1),
                        "distAfterM": round(v[2] / v[3], 1)} for g, v in agg.items()),
                      key=lambda r: -(r["distAfterM"] - r["distBeforeM"]) * max(r["weight"], 1))
    out = jsonable({
        "mode": "close", "scope": scope, "scopeName": _scope_name(c, y, scope), "k": k, "level": lvl,
        "demandUnit": "oa" if use_oa else "area", "demandPoints": len(areas),
        "weight": used, "weightFallback": used != weight, "farM": far_m,
        "candidateCount": len(facs), "steps": out_steps,
        "totalAddedKmPpl": round(sum(s["addedCost"] for s in steps) / 1000, 1),
        "totalNewlyFar": round(sum(s["newlyFar"] for s in steps)),
        "affectedAreas": affected[:50],
        "leastImpact": [{"histId": r["histId"], "name": r["name"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"],
                         "addedKmPpl": round(r["addedCost"] / 1000, 1), "newlyFar": round(r["newlyFar"]),
                         "areasAffected": r["areasAffected"], "soleHubPpltn": hub.get(r["histId"])} for r in singles[:15]],
        "mostCritical": [{"histId": r["histId"], "name": r["name"], "addr": r["addr"],
                          "addedKmPpl": round(r["addedCost"] / 1000, 1), "newlyFar": round(r["newlyFar"]),
                          "areasAffected": r["areasAffected"], "soleHubPpltn": hub.get(r["histId"])} for r in singles[::-1][:10]],
        "caveat": CAVEAT, "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=3600)
    return out


def plan_open(c: Connection, scope: str, k: int, weight: str, level: int | None = None,
              calc_run_id: str | None = None) -> dict[str, Any]:
    _validate(scope, k, weight)
    run = resolve_calc_run(c, calc_run_id)
    lvl, y, far_m = _level(run, level), run["stat_year"], float(run["params"].get("farKm", 2)) * 1000
    key = _key("open", run["calc_run_id"], scope=scope, k=k, weight=weight, level=lvl)
    if hit := cache.get(key):
        return json.loads(hit)
    cur = {r[0]: float(r[1]) for r in c.execute(text("""
        SELECT a.adm_cd, n.dist_m FROM mart.admin_area a
          JOIN mart.area_nearest n ON n.calc_run_id = :run AND n.adm_cd = a.adm_cd AND n.rank = 1
         WHERE a.stat_year = :y AND a.level = :lvl AND a.adm_cd LIKE :scope || '%'"""),
        {"run": run["calc_run_id"], "y": y, "lvl": lvl, "scope": scope})}
    if not cur:
        raise not_found("NO_AREA", f"범위 {scope} 에 계산된 지역이 없습니다.")
    near: dict[str, list[tuple[str, float]]] = {}
    for s, a, d in c.execute(text("""
            SELECT s.adm_cd, a.adm_cd, ST_Distance(s.rep_point_5179, a.rep_point_5179)
              FROM mart.admin_area s
              JOIN mart.admin_area a ON a.stat_year = s.stat_year AND a.level = s.level
                                    AND a.adm_cd LIKE :scope || '%'
                                    AND ST_DWithin(s.rep_point_5179, a.rep_point_5179, :r)
             WHERE s.stat_year = :y AND s.level = :lvl AND s.adm_cd LIKE :scope || '%'"""),
            {"y": y, "lvl": lvl, "scope": scope, "r": OPEN_RADIUS_M}):
        if a in cur:
            near.setdefault(s, []).append((a, float(d)))
    w, used = _weights(c, y, list(cur), weight)
    steps = greedy_open(cur, w, near, k, far_m)
    names = _area_names(c, y, list(cur))
    pts = {r[0]: (r[1], r[2]) for r in c.execute(text("""
        SELECT adm_cd, ST_Y(rep_point), ST_X(rep_point) FROM mart.admin_area
         WHERE stat_year = :y AND adm_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": [s["siteCd"] for s in steps]})}
    after = dict(cur)
    for st in steps:
        for a, d in near[st["siteCd"]]:
            after[a] = min(after[a], d)
    improved = sorted(({"admCd": a, "admNm": names.get(a), "weight": round(w.get(a, 0)), "distBeforeM": round(cur[a], 1),
                        "distAfterM": round(after[a], 1)} for a in cur if after[a] < cur[a]),
                      key=lambda r: -(r["distBeforeM"] - r["distAfterM"]) * max(r["weight"], 1))
    out = jsonable({
        "mode": "open", "scope": scope, "scopeName": _scope_name(c, y, scope), "k": k, "level": lvl,
        "weight": used, "weightFallback": used != weight, "farM": far_m, "candidateCount": len(near),
        "steps": [{**st, "siteNm": names.get(st["siteCd"]), "lat": pts.get(st["siteCd"], (None, None))[0],
                   "lon": pts.get(st["siteCd"], (None, None))[1], "gainKmPpl": round(st["gain"] / 1000, 1),
                   "newlyNear": round(st["newlyNear"])} for st in steps],
        "totalGainKmPpl": round(sum(s["gain"] for s in steps) / 1000, 1),
        "totalNewlyNear": round(sum(s["newlyNear"] for s in steps)),
        "improvedAreas": improved[:50],
        "caveat": CAVEAT, "meta": meta_of(run),
    })
    cache.set(key, json.dumps(out, ensure_ascii=False), ttl=3600)
    return out


def _area_names(c: Connection, y: int, cds: list[str]) -> dict[str, str]:
    return {r[0]: r[1] for r in c.execute(text("""
        SELECT a.adm_cd, coalesce(pa.adm_nm || ' ', '') || a.adm_nm FROM mart.admin_area a
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE a.stat_year = :y AND a.adm_cd = ANY(CAST(:c AS text[]))"""), {"y": y, "c": cds})}


def _scope_name(c: Connection, y: int, scope: str) -> str | None:
    return c.execute(text("""SELECT adm_nm FROM mart.area_population WHERE stat_year = :y AND adm_cd = :s"""),
                     {"y": y, "s": scope}).scalar()
