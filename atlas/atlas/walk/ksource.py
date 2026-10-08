"""여러 시설에서 동시에 퍼져 나가며 꼭짓점마다 '가장 가까운 시설 k곳'을 찾는 다익스트라.

scipy 의 다중 출발 다익스트라(min_only)는 가장 가까운 한 곳만 줍니다. What-if·은행 지점 영향평가는
'이 시설이 문을 닫으면 다음으로 가까운 곳'이 필요해 k곳(라벨 k개)이 있어야 합니다.
꼭짓점마다 서로 다른 시설 라벨을 거리순으로 최대 k개 확정 — 각 (꼭짓점, 시설) 쌍은 처음 꺼낼 때가 최단 거리입니다.
limit(m) 밖으로는 퍼지지 않아 시골의 빈 도로망은 거의 탐색하지 않습니다.
"""
from __future__ import annotations

import heapq

import numpy as np


def k_nearest(indptr: np.ndarray, indices: np.ndarray, weights: np.ndarray, seeds: list[tuple[float, int, int]],
              k: int, limit: float) -> tuple[np.ndarray, np.ndarray]:
    """seeds = [(시작 거리, 꼭짓점, 시설 번호)] → (src[n, k] int32(-1 = 없음), dist[n, k] float32(inf))."""
    n = len(indptr) - 1
    src = np.full((n, k), -1, dtype=np.int32)
    dist = np.full((n, k), np.inf, dtype=np.float32)
    # numpy 원소를 하나씩 읽으면 느려 memoryview 로 (복사 없음, 파이썬 int/float 로 바로 나옴)
    ip, ix, wt = memoryview(indptr), memoryview(indices), memoryview(weights)
    labels: list[list[int] | None] = [None] * n       # 꼭짓점마다 확정된 시설 번호
    heap = [(float(d), int(v), int(s)) for d, v, s in seeds if d <= limit]
    heapq.heapify(heap)
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        d, v, s = pop(heap)
        lab = labels[v]
        if lab is None:
            lab = labels[v] = []
        elif len(lab) >= k or s in lab:
            continue
        j = len(lab)
        lab.append(s)
        src[v, j] = s
        dist[v, j] = d
        for e in range(ip[v], ip[v + 1]):
            nd = d + wt[e]
            if nd > limit:
                continue
            u = ix[e]
            lu = labels[u]
            if lu is not None and (len(lu) >= k or s in lu):
                continue
            push(heap, (nd, u, s))
    return src, dist
