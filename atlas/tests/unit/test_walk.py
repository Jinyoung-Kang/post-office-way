"""② 도보 그래프·k-최근접 탐색 — 무작위 그래프에서 '시설마다 따로 최단 거리'를 구한 정답과 비교."""
import numpy as np
import pytest

np_ = pytest.importorskip("numpy")
sp = pytest.importorskip("scipy.sparse.csgraph")
osmium = pytest.importorskip("osmium")

from atlas.walk.graph import Graph, build, to_csr, walkable  # noqa: E402
from atlas.walk.ksource import k_nearest  # noqa: E402


def random_graph(n=400, m=1200, seed=7):
    rng = np.random.default_rng(seed)
    u = rng.integers(0, n, m).astype(np.int32)
    v = rng.integers(0, n, m).astype(np.int32)
    w = rng.uniform(10, 300, m).astype(np.float32)
    return to_csr(n, u, v, w)


@pytest.mark.parametrize("k", [1, 2, 3])
def test_k_nearest_matches_brute_force(k):
    import scipy.sparse as ss

    g = random_graph()
    n = len(g.indptr) - 1
    mat = ss.csr_matrix((g.weights.astype(np.float64), g.indices, g.indptr), shape=(n, n))
    sources = [5, 50, 120, 220, 330, 390]
    offset = [0.0, 25.0, 0.0, 10.0, 0.0, 40.0]               # 시설 → 가까운 꼭짓점 붙임 거리
    limit = 900.0
    src, dist = k_nearest(g.indptr, g.indices, g.weights, [(o, v, i) for i, (v, o) in enumerate(zip(sources, offset))],
                          k, limit)
    full = sp.dijkstra(mat, directed=False, indices=sources) + np.array(offset)[:, None]   # (시설, 꼭짓점)
    full[full > limit + 1e-3] = np.inf
    for v in range(n):
        want = np.sort(full[:, v])[:k]
        got = dist[v][: k]
        assert np.allclose(np.where(np.isinf(want), -1, want), np.where(np.isinf(got), -1, got), atol=0.05), v
        for j in range(k):                                   # 라벨의 시설이 실제 그 거리
            if src[v, j] >= 0:
                assert abs(full[src[v, j], v] - dist[v, j]) < 0.05


def test_walkable_rules():
    assert walkable({"highway": "footway"}) and walkable({"highway": "trunk"})
    assert not walkable({"highway": "motorway"}) and not walkable({"building": "yes"})
    assert not walkable({"highway": "residential", "foot": "no"})
    assert not walkable({"highway": "service", "access": "private"})
    assert walkable({"highway": "service", "access": "private", "foot": "yes"})


def test_build_splits_at_junctions_and_skips_non_walkable(tmp_path):
    from osmium.osm import mutable

    p = tmp_path / "t.osm.pbf"
    pts = {1: (127.0, 37.5), 2: (127.001, 37.5), 3: (127.002, 37.5), 4: (127.001, 37.501), 5: (127.003, 37.5),
           6: (127.0, 37.52), 7: (127.0, 37.505)}
    with osmium.SimpleWriter(str(p)) as w:
        for i, xy in pts.items():
            w.add_node(mutable.Node(id=i, location=xy))
        w.add_way(mutable.Way(id=10, nodes=[1, 2, 3], tags={"highway": "residential"}))
        w.add_way(mutable.Way(id=11, nodes=[2, 4], tags={"highway": "footway"}))
        w.add_way(mutable.Way(id=12, nodes=[3, 5], tags={"highway": "motorway"}))      # 걸을 수 없음
        w.add_way(mutable.Way(id=13, nodes=[1, 7, 6], tags={"highway": "path"}))         # 2.2km → 150m 마다 꼭짓점
        w.add_way(mutable.Way(id=14, nodes=[1, 4], tags={"building": "yes"}))
    g = build(p, tmp_path)
    assert isinstance(g, Graph)
    edges = set()
    for a in range(g.n):
        for e in range(g.indptr[a], g.indptr[a + 1]):
            edges.add((a, int(g.indices[e])))
    assert all((b, a) in edges for a, b in edges)            # 무방향
    lonlat = {(round(float(x), 4), round(float(y), 4)) for x, y in zip(g.lon, g.lat)}
    assert (127.003, 37.5) not in lonlat                     # 고속도로 끝점은 그래프에 없음
    assert (127.001, 37.5) in lonlat and (127.002, 37.5) in lonlat   # 교차점·끝점
    assert g.meta["ways"] == 3
    # 2번(교차점)에서 1→2 와 2→3 이 갈라져야 함: 1-2 간선 길이 ≈ 88m
    i1 = [i for i in range(g.n) if round(float(g.lon[i]), 4) == 127.0 and round(float(g.lat[i]), 4) == 37.5][0]
    nb = {round(float(g.lon[g.indices[e]]), 4): float(g.weights[e]) for e in range(g.indptr[i1], g.indptr[i1 + 1])}
    assert nb[127.001] == pytest.approx(88.3, abs=0.5)
    assert len(nb) == 2                                      # 2번 쪽 + path 첫 150m 꼭짓점(7번)


def test_save_load_roundtrip(tmp_path):
    g = random_graph(20, 40)
    g.meta = {"a": 1}
    g.save(tmp_path / "g.npz")
    h = Graph.load(tmp_path / "g.npz")
    assert np.array_equal(g.indptr, h.indptr) and h.meta == {"a": 1}
