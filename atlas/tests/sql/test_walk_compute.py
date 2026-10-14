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

    from atlas.calc.runs import data_version

    state = lambda: c2.execute(text("SELECT status, finished_at FROM mart.walk_run WHERE calc_run_id = :r"),  # noqa: E731
                               {"r": rid}).one()
    with engine.connect() as c2:
        done_before, version_before = state(), data_version(c2, {"calc_run_id": rid})
    seen = []

    def boom(*a, **k):
        with engine.connect() as c3:                        # 계산하는 동안에도 이전 결과의 상태가 그대로여야 함
            seen.append(c3.execute(text("SELECT status FROM mart.walk_run WHERE calc_run_id = :r"), {"r": rid}).scalar())
        raise RuntimeError("적재 단계 실패")

    monkeypatch.setattr(compute, "_copy_rows", boom)
    with pytest.raises(RuntimeError):
        compute.run_walk(str(rid), graph=g)
    with engine.connect() as c2:
        assert count() == before
        # 상태도 이전 결과(DONE·완료 시각)를 가리켜야 화면 메타·캐시 키(data_version)가 남은 데이터와 맞음
        # (예전에는 시작할 때 RUNNING, 실패하면 FAILED 로 바뀌어 '도보 계산 전'으로 보였음)
        assert seen == ["DONE"]
        assert state() == done_before and data_version(c2, {"calc_run_id": rid}) == version_before


def test_first_walk_failure_is_recorded(terrain, engine, monkeypatch):
    """이전 결과가 없는 첫 계산이 실패하면 FAILED 로 남김."""
    from atlas.walk import compute

    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
    rid = run_calc(stat_year=2024, levels=[2])

    def boom(*a, **k):
        raise RuntimeError("적재 단계 실패")

    monkeypatch.setattr(compute, "_copy_rows", boom)
    with pytest.raises(RuntimeError):
        compute.run_walk(str(rid), graph=grid_graph(engine))
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM mart.walk_run WHERE calc_run_id = :r"), {"r": rid}).scalar() == "FAILED"


def test_stale_graph_version_is_not_used(terrain, engine, monkeypatch, tmp_path):
    """그래프 규칙(GRAPH_VERSION)이 바뀌었는데 예전 그래프가 남아 있으면 쓰지 않고 다시 만들라고 알림 (R12)."""
    from atlas.core.config import get_settings
    from atlas.walk import compute, osm
    from atlas.walk.graph import Graph

    monkeypatch.setattr(get_settings(), "osm_dir", str(tmp_path))
    run_calc(stat_year=2024, levels=[2])
    g = Graph(np.array([0, 0]), np.array([], dtype=np.int32), np.array([]), np.array([127.0]), np.array([37.0]),
              {"graphVersion": osm.GRAPH_VERSION - 1})
    g.save(osm.paths()["graph"])
    out = compute.run_walk()
    assert "skipped" in out and "make osm" in out["skipped"]



def test_walk_with_two_boundary_years(terrain, engine):
    """경계를 두 해 적재해 둔 상태(연례 갱신 — 이전 해 행은 지우지 않음)에서도 도보 지표가 그 해 경계로 한 번씩만 들어가야 함.
    예전에는 admin_area 를 연도 없이 조인해 같은 (계산, 지역, 지표)가 두 번 INSERT 되어 PK 위반으로 도보 계산이 늘 실패했음."""
    from atlas.walk.compute import WALK_METRICS, run_walk

    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO mart.admin_area (adm_cd, stat_year, adm_nm, level, parent_cd, geom, geom_5179, geom_simple,
                                         rep_point, rep_point_5179, src_crs)
            SELECT adm_cd, 2025, adm_nm, level, parent_cd, geom, geom_5179, geom_simple, rep_point, rep_point_5179, src_crs
              FROM mart.admin_area WHERE stat_year = 2024"""))
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
    rid = run_calc(stat_year=2024, levels=[2])
    run_walk(str(rid), graph=grid_graph(engine))
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM mart.walk_run WHERE calc_run_id = :r"), {"r": rid}).scalar() == "DONE"
        assert c.execute(text("""SELECT count(*) FROM mart.access_metric
                                  WHERE calc_run_id = :r AND adm_cd = '99010' AND metric_code = ANY(:m)"""),
                         {"r": rid, "m": list(WALK_METRICS)}).scalar() == len(WALK_METRICS)


def _k1_setup(engine):
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
        add_oa(c, "99010010000002", 1_000, 8_000, 300)
        add_oa(c, "99010010000003", 2_000, 7_500, 50)
        add_branch(c, "K1", 2_000, 7_000, "KB국민은행")
        add_branch(c, "S1", 18_000, 18_000, "신한은행")
    return run_calc(stat_year=2024, levels=[2])


def _k1(engine, rid):
    with engine.connect() as c:
        return c.execute(text("""SELECT walk_now_m, coalesce(walk_lost_ppltn, 0) AS lost, reasons
                                   FROM mart.bank_impact WHERE calc_run_id = :r AND place_id = 'K1'"""), {"r": rid}).one()


def test_walk_rerun_clears_stale_bank_walk_values(terrain, engine, monkeypatch):
    """같은 계산 실행을 다시 도보 계산할 때 이번에 어느 집계구의 '걸어서 가장 가까운 지점'도 아닌 지점은 도보 값이 비어야 함.
    예전에는 이번 결과에 나온 지점만 갱신해, 빠진 지점에 이전 값·사유(NO_ALT_WALK30)·등급이 남았음."""
    from atlas.core.config import get_settings
    from atlas.walk.compute import run_walk

    rid = _k1_setup(engine)
    g = grid_graph(engine)
    run_walk(str(rid), graph=g)
    assert _k1(engine, rid).lost == 50
    monkeypatch.setattr(get_settings(), "walk_limit_m", 400.0)      # OA3 → K1 500m 가 한도 밖
    run_walk(str(rid), graph=g)
    k1 = _k1(engine, rid)
    assert k1.walk_now_m is None and k1.lost == 0 and "NO_ALT_WALK30" not in k1.reasons


def test_walk_uses_bank_set_of_its_calc_run(terrain, engine):
    """도보가 쓰는 은행 지점은 그 계산 실행(bank_impact)의 지점 — 계산 뒤 새로 수집된 지점이 섞이면, 그 지점을 가장 가까운
    지점으로 둔 집계구가 영향평가에서 조용히 빠지고 지역 지표와 기준이 어긋났음."""
    from atlas.walk.compute import run_walk

    rid = _k1_setup(engine)
    with engine.begin() as c:
        add_branch(c, "K2", 2_000, 7_500, "우리은행")                 # 계산 뒤 OA3 바로 옆에 생긴 지점
    run_walk(str(rid), graph=grid_graph(engine))
    with engine.connect() as c:
        stray = c.execute(text("""SELECT DISTINCT w.target FROM mart.oa_walk w
                                    LEFT JOIN mart.bank_impact b ON b.calc_run_id = w.calc_run_id AND b.place_id = w.target
                                   WHERE w.calc_run_id = :r AND w.kind = 'BANK' AND b.place_id IS NULL"""), {"r": rid}).all()
    assert stray == [] and _k1(engine, rid).lost == 50
