"""② 도보 계산(walk/compute.py) — 소형 지형에 500m 격자 도로를 깔아 손 계산과 비교.

OA1(5k,3k) 100명 → 금융 우체국 F1(5k,2k) 격자로 1,000m · 은행 K1(2k,7k) 7,000m(한도 밖)
OA2(1k,8k) 300명 → F1 10,000m(한도 밖) · K1 2,000m / OA3(2k,7.5k) 50명 → K1 500m, 우체국은 한도 밖
→ 걸어서 K1 을 쓰는 주민 OA2·OA3. 닫히면 둘 다 30분 안 대체 없음, 그중 지금 30분(1,440m) 안인 OA3 50명만 '잃는' 주민.
간선 길이는 구면 하버사인이라 타원체 거리와 0.2% 안팎 차이 → 상대 0.5% 허용.
"""
import numpy as np
import pytest
from sqlalchemy import text

pytest.importorskip("scipy")

from atlas.calc.runner import run_calc  # noqa: E402
from atlas.walk.graph import haversine, to_csr  # noqa: E402
from tests.sql.conftest import X0, Y0  # noqa: E402
from tests.sql.test_bank_impact import add_branch  # noqa: E402
from tests.sql.test_extras import add_oa  # noqa: E402

pytestmark = pytest.mark.db
STEP, N = 500, 41                                     # 0~20km, 41×41 꼭짓점


def grid_graph(engine):
    with engine.connect() as c:
        pts = c.execute(text("""
            SELECT i, j, ST_X(p), ST_Y(p) FROM (
              SELECT i, j, ST_Transform(ST_SetSRID(ST_MakePoint(:x0 + i * :s, :y0 + j * :s), 5179), 4326) AS p
                FROM generate_series(0, :n - 1) i, generate_series(0, :n - 1) j) t ORDER BY i, j"""),
                        {"x0": X0, "y0": Y0, "s": STEP, "n": N}).all()
    lon = np.array([p[2] for p in pts])
    lat = np.array([p[3] for p in pts])
    vid = lambda i, j: i * N + j  # noqa: E731
    u, v = [], []
    for i in range(N):
        for j in range(N):
            if i + 1 < N:
                u.append(vid(i, j)); v.append(vid(i + 1, j))
            if j + 1 < N:
                u.append(vid(i, j)); v.append(vid(i, j + 1))
    u, v = np.array(u, dtype=np.int32), np.array(v, dtype=np.int32)
    g = to_csr(N * N, u, v, haversine(lon[u], lat[u], lon[v], lat[v]).astype(np.float32))
    g.lon, g.lat, g.meta = lon, lat, {"test": True}
    return g


def test_walk_distances_metrics_and_bank_impact(terrain, engine):
    from atlas.walk.compute import run_walk

    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
        add_oa(c, "99010010000002", 1_000, 8_000, 300)
        add_oa(c, "99010010000003", 2_000, 7_500, 50)
        add_branch(c, "K1", 2_000, 7_000, "KB국민은행")
        add_branch(c, "S1", 18_000, 18_000, "신한은행")
    rid = run_calc(stat_year=2024, levels=[2])
    res = run_walk(str(rid), graph=grid_graph(engine))
    assert res["oa"] == 3 and res["postReached"] == 1 and res["bankReached"] == 2
    with engine.connect() as c:
        w = {(r.kind, r.oa_cd, r.rank): (r.target, r.walk_m) for r in c.execute(text(
            "SELECT * FROM mart.oa_walk WHERE calc_run_id = :r"), {"r": rid})}
        m = {r[0]: float(r[1]) for r in c.execute(text("""SELECT metric_code, value FROM mart.access_metric
                WHERE calc_run_id = :r AND adm_cd = '99010' AND metric_code LIKE '%WALK%'"""), {"r": rid})}
        k1 = c.execute(text("SELECT * FROM mart.bank_impact WHERE calc_run_id = :r AND place_id = 'K1'"), {"r": rid}).one()
        run = c.execute(text("SELECT status, stats FROM mart.walk_run WHERE calc_run_id = :r"), {"r": rid}).one()
    assert w[("POST", "99010010000001", 1)][1] == pytest.approx(1_000, rel=0.005)
    assert ("POST", "99010010000002", 1) not in w             # 3km 안에 닿는 우체국 없음
    assert ("BANK", "99010010000001", 1) not in w             # K1 은 격자로 7km
    assert w[("BANK", "99010010000003", 1)] == ("K1", pytest.approx(500, rel=0.005))
    assert m["POPW_FIN_WALK_M"] == pytest.approx((100 * 1_000 + 350 * 3_000) / 450, rel=0.005)
    assert m["WALK30_NO_FIN_PPLTN"] == 350 and m["WALK30_NO_FIN_SHARE"] == pytest.approx(77.8, abs=0.05)
    assert m["WALK30_NO_CASH_PPLTN"] == 300                   # OA3 은 은행 500m, OA1 은 우체국 1,000m
    assert float(k1.walk_now_m) == pytest.approx((300 * 2_000 + 50 * 500) / 350, rel=0.005) and k1.walk_alt_m is None
    assert k1.walk_lost_ppltn == 50 and "NO_ALT_WALK30" in k1.reasons
    assert run.status == "DONE"


def test_walk_is_idempotent_and_skips_without_graph(terrain, engine, monkeypatch, tmp_path):
    from atlas.core.config import get_settings
    from atlas.walk.compute import run_walk

    monkeypatch.setattr(get_settings(), "osm_dir", str(tmp_path))
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
    rid = run_calc(stat_year=2024, levels=[2])
    assert "skipped" in run_walk(str(rid))                      # 그래프 파일 없음
    g = grid_graph(engine)
    run_walk(str(rid), graph=g)
    run_walk(str(rid), graph=g)                                  # 다시 돌려도 중복 없음
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM mart.oa_walk WHERE calc_run_id = :r AND kind = 'POST'"),
                         {"r": rid}).scalar() == 1              # 3km 안 우체국은 F1 하나 (F2·F3 는 격자로 16km·13km)


def test_walk_failure_keeps_previous_results(terrain, engine, monkeypatch):
    """다시 계산하다 중간(적재 단계)에 실패하면 이전 도보 결과가 그대로 남아야 함 — 지우기·적재·지표가 한 트랜잭션."""
    from atlas.walk import compute

    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
    rid = run_calc(stat_year=2024, levels=[2])
    g = grid_graph(engine)
    compute.run_walk(str(rid), graph=g)
    count = lambda: c2.execute(text("SELECT count(*) FROM mart.oa_walk WHERE calc_run_id = :r"),  # noqa: E731
                               {"r": rid}).scalar()
    with engine.connect() as c2:
        before = count()
    assert before > 0

    def boom(*a, **k):
        raise RuntimeError("적재 단계 실패")

    monkeypatch.setattr(compute, "_copy_rows", boom)
    with pytest.raises(RuntimeError):
        compute.run_walk(str(rid), graph=g)
    with engine.connect() as c2:
        assert count() == before
        assert c2.execute(text("SELECT status FROM mart.walk_run WHERE calc_run_id = :r"), {"r": rid}).scalar() == "FAILED"
