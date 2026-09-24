"""지표 SQL — 소형 지형에서 손 계산 기대값과 비교 (FR-301~303, 거리 ±1m)."""
import math

import pytest
from sqlalchemy import text

from atlas.calc.runner import run_calc

pytestmark = pytest.mark.db
A, B, C, D = "99010", "99020", "99030", "99040"


def d(dx, dy):
    return math.hypot(dx, dy)


def metrics(engine, rid):
    with engine.connect() as c:
        rows = c.execute(text("SELECT adm_cd, metric_code, value FROM mart.access_metric WHERE calc_run_id = :r"),
                         {"r": rid}).all()
    return {(a, m): (float(v) if v is not None else None) for a, m, v in rows}


def test_spatial_join(terrain, engine):
    run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        m = dict(c.execute(text("""SELECT h.post_id, f.adm_cd FROM mart.facility_area_map f
                                   JOIN mart.post_facility_hist h USING (hist_id) WHERE f.method = 'CONTAINS'""")).all())
    assert m == {"F1": A, "F2": B, "F3": C, "F4": D, "F5": D}


def test_nearest_top3(terrain, engine):
    rid = run_calc(stat_year=2024, levels=[2])
    ids = {v: k for k, v in terrain.items()}
    with engine.connect() as c:
        rows = c.execute(text("SELECT adm_cd, rank, hist_id, dist_m FROM mart.area_nearest WHERE calc_run_id = :r"),
                         {"r": rid}).all()
    got = {(a, r): (ids[h], float(dm)) for a, r, h, dm in rows}
    expected = {
        (A, 1): ("F1", 3000), (A, 2): ("F2", d(10_000, 4_000)), (A, 3): ("F3", 11_000),
        (B, 1): ("F2", 4000), (B, 2): ("F1", d(10_000, 3_000)), (B, 3): ("F3", d(10_000, 11_000)),
        (C, 1): ("F3", 1000), (C, 2): ("F2", d(10_000, 6_000)), (C, 3): ("F1", 13_000),
        (D, 1): ("F2", 6000), (D, 2): ("F3", d(10_000, 1_000)), (D, 3): ("F1", d(10_000, 13_000)),
    }
    assert set(got) == set(expected)
    for k, (fac, dist) in expected.items():
        assert got[k][0] == fac, k
        assert abs(got[k][1] - dist) <= 1.0, (k, got[k][1], dist)


def test_metric_values(terrain, engine):
    rid = run_calc(stat_year=2024, levels=[2])
    m = metrics(engine, rid)
    # 모든 지표 × 지역 4개
    codes = {k[1] for k in m}
    assert codes == {"NEAREST_FIN_DIST_M", "FAC_CNT_R1KM", "FAC_CNT_R2KM", "FAC_CNT_R5KM", "HAS_365",
                     "LUNCH_CLOSED_RATIO", "ACCESS_GAP_SCORE"}
    assert len(m) == len(codes) * 4
    assert [m[(x, "NEAREST_FIN_DIST_M")] for x in (A, B, C, D)] == [3000, 4000, 1000, 6000]
    assert [m[(x, "FAC_CNT_R5KM")] for x in (A, B, C, D)] == [1, 1, 1, 0]
    assert [m[(x, "FAC_CNT_R2KM")] for x in (A, B, C, D)] == [0, 0, 1, 0]
    assert [m[(x, "HAS_365")] for x in (A, B, C, D)] == [0, 0, 0, 1]
    assert all(m[(x, "LUNCH_CLOSED_RATIO")] is None for x in (A, B, C, D))  # 우체국 5개 미만
    # 0.6×minmax(거리 1000~6000) + 0.4×minmax(노령화 100~400)
    assert m[(A, "ACCESS_GAP_SCORE")] == pytest.approx(24.00, abs=0.01)
    assert m[(B, "ACCESS_GAP_SCORE")] == pytest.approx(49.33, abs=0.01)
    assert m[(C, "ACCESS_GAP_SCORE")] == pytest.approx(26.67, abs=0.01)
    assert m[(D, "ACCESS_GAP_SCORE")] == pytest.approx(100.00, abs=0.01)


def test_lunch_ratio_needs_5_offices(clean, engine):
    from tests.sql.conftest import add_area, add_fac, add_pop

    with clean.begin() as c:
        add_area(c, "99010", 0, 0, 10_000, 10_000)
        add_pop(c, "99010", 100, 100)
        for i in range(5):
            add_fac(c, f"L{i}", 1_000 + i * 1_000, 5_000, lunch="Y" if i < 2 else "N")
        add_fac(c, "BOX", 5_000, 6_000, div=2, finance=None, fin=False, lunch="Y")  # 우체통은 분모 제외
    rid = run_calc(stat_year=2024, levels=[2])
    assert metrics(engine, rid)[("99010", "LUNCH_CLOSED_RATIO")] == 40.0


def test_reproducible(terrain, engine):
    """같은 입력이면 같은 값 (NFR-03). 이후 새 시설이 생겨도 이전 calc_run 스냅샷 기준 재계산은 동일."""
    r1 = run_calc(stat_year=2024, levels=[2])
    r2 = run_calc(stat_year=2024, levels=[2])
    assert metrics(engine, r1) == metrics(engine, r2)


def test_dq_spatial_join_miss(terrain, engine):
    from tests.sql.conftest import add_fac

    with engine.begin() as c:
        add_fac(c, "SEA", 21_000, 5_000)       # 경계 1km 밖 → NEAREST 보정 + 이슈
        add_fac(c, "FAR", 90_000, 90_000)      # 범위 밖(20km 초과) → 이슈 아님
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        issues = c.execute(text("""SELECT target_key, detail->>'method' FROM ops.dq_issue
                                   WHERE calc_run_id = :r AND check_code = 'SPATIAL_JOIN_MISS'"""), {"r": rid}).all()
        checks = dict(c.execute(text("SELECT check_code, issue_count FROM ops.dq_check WHERE calc_run_id = :r"),
                                {"r": rid}).all())
    assert [m for _, m in issues] == ["NEAREST"]
    assert checks == {"SPATIAL_JOIN_MISS": 1, "GEOM_INVALID": 0}


def test_calc_fails_cleanly_without_areas(clean, engine):
    with pytest.raises(RuntimeError):
        run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        st = c.execute(text("SELECT status FROM mart.calc_run")).scalar_one()
    assert st == "FAILED"


def test_kosis_aged_metrics(terrain, engine):
    """고령인구 지표 — KOSIS 적재분이 있으면 계산, 2km 밖 고령인구는 읍면동 판정 후 시군구 합."""
    from tests.sql.conftest import add_area

    with engine.begin() as c:
        # 지역 D(99040) 아래 읍면동 2개: 서쪽 절반(F2 에서 먼 쪽)·동쪽 절반
        add_area(c, "99040010", 10_000, 10_000, 15_000, 20_000, level=3, parent="99040")
        add_area(c, "99040020", 15_000, 10_000, 20_000, 20_000, level=3, parent="99040")
        for cd, tot, aged in [("99010", 1000, 100), ("99040", 4000, 900), ("99040010", 2000, 500), ("99040020", 2000, 400)]:
            c.execute(text("""INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn,
                                  aged65_ratio, match_method) VALUES (:cd, 2024, '202412', :t, :a, round(100.0*:a/:t, 2), 'NAME')"""),
                      {"cd": cd, "t": tot, "a": aged})
    rid = run_calc(stat_year=2024, levels=[2, 3])
    m = metrics(engine, rid)
    assert m[("99010", "AGED65_RATIO")] == 10.0 and m[("99040", "AGED65_PPLTN")] == 900
    assert ("99020", "AGED65_PPLTN") not in m                  # KOSIS 값 없는 지역은 행 없음
    # 읍면동 대표점 (12.5k,15k)·(17.5k,15k) → 최근접 F2(15k,9k) 거리 6.5km·6.5km > 2km
    assert m[("99040010", "AGED65_FAR_PPLTN")] == 500 and m[("99040020", "AGED65_FAR_PPLTN")] == 400
    assert m[("99040", "AGED65_FAR_PPLTN")] == 900              # 시군구 = 하위 합
    assert ("99010", "AGED65_FAR_PPLTN") not in m               # 읍면동이 없는 시군구는 합할 대상 없음


def test_prune_keeps_recent_calc_runs(terrain, engine):
    """make prune — 오래된 계산(지표·최근접)은 지우고 최근 N개 + 가장 최근 DONE 은 남김."""
    import argparse

    from atlas.collector.cli import cmd_prune

    ids = [run_calc(stat_year=2024, levels=[2]) for _ in range(3)]
    cmd_prune(argparse.Namespace(keep=3, keep_calc=1))
    with engine.connect() as c:
        left = [r[0] for r in c.execute(text("SELECT calc_run_id FROM mart.calc_run"))]
        metrics = c.execute(text("SELECT count(DISTINCT calc_run_id) FROM mart.access_metric")).scalar_one()
    assert left == [ids[-1]] and metrics == 1
