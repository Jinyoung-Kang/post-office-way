"""What-if — 손 계산 기대값 + 부분 재계산 = 전체 재계산 동등성 20회 (FR-401, ADR-005)."""
import itertools
import random

import pytest
from sqlalchemy import text

from atlas.api.common import resolve_calc_run
from atlas.api.services.whatif import get_scenario, partial_recompute, recompute_all, run_whatif
from atlas.calc.runner import run_calc

pytestmark = pytest.mark.db


def test_remove_one(terrain, engine):
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.begin() as c:
        out = run_whatif(c, str(rid), [terrain["F2"]], level=2)
    by = {a["admCd"]: a for a in out["areas"]}
    assert set(by) == {"99020", "99040"}                       # F2 가 rank1 인 지역만
    assert by["99020"]["newNearestHistId"] == terrain["F1"]
    assert abs(by["99020"]["distAfterM"] - 10440.31) <= 1
    assert by["99040"]["newNearestHistId"] == terrain["F3"]
    assert abs(by["99040"]["distAfterM"] - 10049.88) <= 1
    assert out["summary"]["affectedAreas"] == 2 and out["summary"]["affectedPpltn"] == 6000
    # 멱등 — 같은 요청은 같은 scenario
    with engine.begin() as c:
        again = run_whatif(c, str(rid), [terrain["F2"]], level=2)
        assert again["scenarioId"] == out["scenarioId"]
        assert get_scenario(c, out["scenarioId"])["summary"] == out["summary"]


def test_remove_all_fin_leaves_no_facility(terrain, engine):
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.begin() as c:
        out = run_whatif(c, str(rid), [terrain["F1"], terrain["F2"], terrain["F3"]], level=2)
    assert out["summary"]["affectedAreas"] == 4
    assert out["summary"]["areasWithoutFacility"] == 4
    assert all(a["distAfterM"] is None for a in out["areas"])


def test_non_fin_facility_has_no_effect(terrain, engine):
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.begin() as c:
        out = run_whatif(c, str(rid), [terrain["F4"]], level=2)
    assert out["summary"]["affectedAreas"] == 0


def test_validation(terrain, engine):
    from atlas.api.errors import ApiError

    rid = run_calc(stat_year=2024, levels=[2])
    with engine.begin() as c:
        with pytest.raises(ApiError) as e:
            run_whatif(c, str(rid), [], level=2)
        assert e.value.status == 400
        with pytest.raises(ApiError) as e:
            run_whatif(c, str(rid), [1, 2, 3, 4, 5, 6], level=2)
        assert e.value.status == 400
        with pytest.raises(ApiError) as e:
            run_whatif(c, str(rid), [987654321], level=2)
        assert e.value.code == "FACILITY_NOT_FOUND"


def test_partial_equals_full_random(clean, engine):
    """무작위 지형(지역 16개·시설 60개)에서 무작위 제외 조합 20회: 부분 재계산 = 전체 재계산."""
    from tests.sql.conftest import add_area, add_fac, add_pop

    rnd = random.Random(20260924)
    with clean.begin() as c:
        for i, j in itertools.product(range(4), range(4)):
            cd = f"98{i}{j}0"
            add_area(c, cd, i * 5_000, j * 5_000, (i + 1) * 5_000, (j + 1) * 5_000)
            add_pop(c, cd, rnd.randint(100, 5000), rnd.uniform(50, 400))
        fin_ids = []
        for k in range(60):
            fin = rnd.random() < 0.7
            hid = add_fac(c, f"R{k}", rnd.uniform(-3_000, 23_000), rnd.uniform(-3_000, 23_000),
                          finance="09:00~16:30" if fin else "00:00~00:00", fin=fin)
            if fin:
                fin_ids.append(hid)
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        run = resolve_calc_run(c, str(rid))
        base = {a: (h, d) for a, h, d in c.execute(text(
            "SELECT adm_cd, hist_id, dist_m FROM mart.area_nearest WHERE calc_run_id = :r AND rank = 1"), {"r": rid})}
        for trial in range(20):
            removed = sorted(rnd.sample(fin_ids, rnd.randint(1, 5)))
            partial = {r["adm_cd"]: (r["new_hist_id"], r["dist_after_m"]) for r in partial_recompute(c, run, 2, removed)}
            full = recompute_all(c, run, 2, removed)
            merged = {**base, **partial}
            assert merged == full, f"trial {trial} removed={removed}"
