"""⑤ 배치 제안 알고리즘 — 닫기(탐욕 최소 영향)·열기(p-median 탐욕 근사). DB·HTTP 없이 수요 지점과 후보만 받음.

설명·가정은 api/services/plan.py 머리말. 직선거리 기준 — 공식 판단 근거 아님.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
