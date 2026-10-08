"""② 도보 그래프 — OpenStreetMap 의 걸을 수 있는 길만 골라 교차점·끝점(+150m 마다 한 점)을 꼭짓점으로 하는 무방향 그래프.

두 번 읽습니다.
  1) 길(highway)에 쓰인 노드 ID 를 세어 두 길 이상이 쓰는 노드 = 교차점
  2) 좌표를 붙여 다시 읽으며 길을 교차점·끝점·150m 간격에서 잘라 간선(길이 m)을 만듦
노드 좌표 캐시는 디스크(sparse_file_array)에 둬 전국 파일도 메모리를 적게 씁니다.
결과는 numpy 배열(.npz) — DB 에 넣지 않습니다(간선 수백만 개를 API DB 에 둘 이유가 없고 백업도 가벼움).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# 걸을 수 있는 길. 고속도로(motorway)·버스 전용·공사 중 등은 뺌. trunk(국도)는 시골에서 실제로 걷는 길이라 포함
WALKABLE = frozenset({
    "footway", "path", "pedestrian", "steps", "living_street", "residential", "service", "unclassified",
    "tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link", "trunk", "trunk_link",
    "track", "cycleway", "road", "bridleway", "corridor",
})
NO = frozenset({"no", "private"})
YES = frozenset({"yes", "designated", "permissive"})
DENSIFY_M = 150.0          # 긴 길에도 이 간격마다 꼭짓점 — 집계구 대표점을 가까운 길에 붙이는 오차를 줄임
R_EARTH = 6_371_008.8


def walkable(tags: Any) -> bool:
    """OSM 태그 → 도보 가능 여부 (foot=no/private 이거나 통행 금지면 제외, foot=yes 는 통행 금지보다 우선)."""
    hw = tags.get("highway")
    if hw not in WALKABLE:
        return False
    foot = tags.get("foot")
    if foot in NO:
        return False
    if tags.get("access") in NO and foot not in YES:
        return False
    return True


def haversine(lon1: np.ndarray, lat1: np.ndarray, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


@dataclass
class Graph:
    """CSR(행 = 꼭짓점) 무방향 그래프 — 간선은 양방향으로 두 번 들어 있음."""
    indptr: np.ndarray        # int64 (n+1)
    indices: np.ndarray       # int32
    weights: np.ndarray       # float32 (m)
    lon: np.ndarray           # float64 (n)
    lat: np.ndarray
    meta: dict[str, Any]

    @property
    def n(self) -> int:
        return len(self.lon)

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, indptr=self.indptr, indices=self.indices, weights=self.weights, lon=self.lon, lat=self.lat,
                 meta=np.array([repr(self.meta)]))
        os.replace(tmp, path)                     # 다 쓴 뒤에만 바꿔치기 — 읽는 쪽이 반쯤 쓴 파일을 보지 않게

    @classmethod
    def load(cls, path: Path) -> Graph:
        import ast

        z = np.load(path, allow_pickle=False)
        return cls(z["indptr"], z["indices"], z["weights"], z["lon"], z["lat"], ast.literal_eval(str(z["meta"][0])))


def _junctions(pbf: str) -> np.ndarray:
    """1차: 걸을 수 있는 길이 쓰는 노드 중 두 번 이상 나오는 것(교차점) — 정렬된 ID 배열."""
    import osmium

    chunks: list[np.ndarray] = []
    fp = osmium.FileProcessor(pbf, osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway"))
    for w in fp:
        if walkable(w.tags):
            refs = np.fromiter((n.ref for n in w.nodes), dtype=np.int64)
            # 닫힌 길(고리)은 처음=끝 노드가 같으므로 한 번만 셈
            chunks.append(refs[:-1] if len(refs) > 1 and refs[0] == refs[-1] else refs)
    if not chunks:
        return np.empty(0, dtype=np.int64)
    ids, counts = np.unique(np.concatenate(chunks), return_counts=True)
    return ids[counts >= 2]


def build(pbf: str | Path, cache_dir: str | Path) -> Graph:
    """pbf → Graph. cache_dir 에 노드 좌표 임시 파일을 만들었다가 지움."""
    import osmium

    t0 = time.monotonic()
    pbf = str(pbf)
    junction = _junctions(pbf)
    log.info("walk graph pass1", extra={"junctions": len(junction), "s": round(time.monotonic() - t0, 1)})

    idx_file = Path(cache_dir) / "node_locations.idx"
    idx_file.unlink(missing_ok=True)
    us: list[np.ndarray] = []
    vs: list[np.ndarray] = []
    ws: list[np.ndarray] = []
    vref: list[np.ndarray] = []
    vlon: list[np.ndarray] = []
    vlat: list[np.ndarray] = []
    ways = bad = 0
    try:
        fp = (osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
              .with_locations(f"sparse_file_array,{idx_file}")
              .with_filter(osmium.filter.KeyFilter("highway")))
        for w in fp:
            if not w.is_way() or not walkable(w.tags):
                continue
            nodes = [(n.ref, n.lon, n.lat) for n in w.nodes if n.location.valid()]
            if len(nodes) < 2:
                bad += 1
                continue
            arr = np.array(nodes, dtype=np.float64)
            refs = np.array([n[0] for n in nodes], dtype=np.int64)          # float64 로 바꾸면 큰 ID 가 뭉개짐
            lon, lat = arr[:, 1], arr[:, 2]
            cum = np.concatenate(([0.0], np.cumsum(haversine(lon[:-1], lat[:-1], lon[1:], lat[1:]))))
            pos = np.searchsorted(junction, refs)
            is_v = (pos < len(junction)) & (junction[np.minimum(pos, len(junction) - 1)] == refs)
            is_v[0] = is_v[-1] = True
            band = np.floor(cum / DENSIFY_M)
            is_v[1:] |= band[1:] > band[:-1]                                 # 150m 띠를 넘는 첫 노드
            k = np.flatnonzero(is_v)
            seg = cum[k[1:]] - cum[k[:-1]]
            keep = seg > 0
            us.append(refs[k[:-1]][keep])
            vs.append(refs[k[1:]][keep])
            ws.append(seg[keep].astype(np.float32))
            vref.append(refs[k])
            vlon.append(lon[k])
            vlat.append(lat[k])
            ways += 1
    finally:
        idx_file.unlink(missing_ok=True)
    if not ways:
        raise RuntimeError("걸을 수 있는 길이 하나도 없습니다 — OSM 파일을 확인하세요.")

    # 꼭짓점 ID(OSM 노드) → 0..n-1
    allref = np.concatenate(vref)
    ids, first = np.unique(allref, return_index=True)
    lon_all, lat_all = np.concatenate(vlon)[first], np.concatenate(vlat)[first]
    u = np.searchsorted(ids, np.concatenate(us)).astype(np.int32)
    v = np.searchsorted(ids, np.concatenate(vs)).astype(np.int32)
    w = np.concatenate(ws)
    g = to_csr(len(ids), u, v, w)
    g.lon, g.lat = lon_all, lat_all
    g.meta = {"ways": ways, "skippedWays": bad, "vertices": int(len(ids)), "edges": int(len(g.indices) // 2),
              "junctions": int(len(junction)), "densifyM": DENSIFY_M, "buildS": round(time.monotonic() - t0, 1)}
    log.info("walk graph built", extra=g.meta)
    return g


def to_csr(n: int, u: np.ndarray, v: np.ndarray, w: np.ndarray) -> Graph:
    """무방향 간선 → CSR. 같은 두 점 사이 간선이 여럿이면 가장 짧은 것만 (scipy 의 csr 은 중복을 더해 버림)."""
    a = np.concatenate([u, v])
    b = np.concatenate([v, u])
    c = np.concatenate([w, w]).astype(np.float32)
    loop = a != b
    a, b, c = a[loop], b[loop], c[loop]
    order = np.lexsort((c, b, a))                  # (a, b) 묶음 안에서 짧은 것이 먼저
    a, b, c = a[order], b[order], c[order]
    first = np.ones(len(a), dtype=bool)
    first[1:] = (a[1:] != a[:-1]) | (b[1:] != b[:-1])
    a, b, c = a[first], b[first], c[first]
    indptr = np.zeros(n + 1, dtype=np.int64)
    indptr[1:] = np.cumsum(np.bincount(a, minlength=n))   # a 는 정렬돼 있으므로 행마다 연속
    return Graph(indptr, b.astype(np.int32), c, np.zeros(n), np.zeros(n), {})
