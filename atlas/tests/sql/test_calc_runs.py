"""'최신 완료 계산 실행' 정의 한 곳 — 완료 시각이 같으면 나중에 만든 실행, 실패·진행 중은 제외."""
import pytest
from sqlalchemy import text

from atlas.calc.runs import LATEST_DONE_ID, latest_done, resolve_calc_run
from atlas.domain.errors import Conflict, Invalid, NotFound

pytestmark = pytest.mark.db


def _run(c, status, created, finished):
    return c.execute(text("""INSERT INTO mart.calc_run (stat_year, facility_as_of, params, status, created_at, finished_at)
                             VALUES (2024, now(), '{}', :s, CAST(:c AS timestamptz), CAST(:f AS timestamptz))
                             RETURNING calc_run_id"""), {"s": status, "c": created, "f": finished}).scalar()


def test_latest_done_tie_and_status(clean):
    with clean.begin() as c:
        assert latest_done(c) is None
        _run(c, "DONE", "2026-01-01 00:00+09", "2026-01-02 00:00+09")
        newer = _run(c, "DONE", "2026-01-01 01:00+09", "2026-01-02 00:00+09")   # 완료 시각 동률 → 나중에 만든 것
        _run(c, "FAILED", "2026-01-03 00:00+09", "2026-01-04 00:00+09")
        running = _run(c, "RUNNING", "2026-01-05 00:00+09", None)
        assert latest_done(c)["calc_run_id"] == newer
        assert c.execute(text(f"SELECT {LATEST_DONE_ID}")).scalar() == newer
        assert resolve_calc_run(c, None)["calc_run_id"] == newer
        with pytest.raises(Conflict):
            resolve_calc_run(c, str(running))
        with pytest.raises(NotFound):
            resolve_calc_run(c, "00000000-0000-0000-0000-000000000000")
        with pytest.raises(Invalid):
            resolve_calc_run(c, "not-a-uuid")


def test_interrupted_calc_is_closed(terrain, engine, monkeypatch):
    """CLI 계산을 Ctrl-C 로 멈추면(KeyboardInterrupt 는 Exception 이 아님) 실행 기록을 FAILED 로 닫아야 함.
    예전에는 RUNNING 으로 남아 2시간 동안 워커의 자동 재계산이 모두 '계산이 이미 실행 중'으로 실패했음."""
    from atlas.calc import runner

    real = runner.run_sql_file

    def interrupt(c, f, p=None):
        if f == "calc/02_area_nearest.sql":
            raise KeyboardInterrupt
        return real(c, f, p)

    monkeypatch.setattr(runner, "run_sql_file", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        st = c.execute(text("SELECT status FROM mart.calc_run ORDER BY created_at DESC LIMIT 1")).scalar()
    assert st == "FAILED" and runner.running_calc() is None


def test_interrupted_osm_refresh_is_closed(clean, monkeypatch, tmp_path):
    """make osm 을 Ctrl-C 로 멈춰도 OSM_WALK 실행 기록을 닫음 — 예전에는 6시간 동안 osm 작업이 '이미 실행 중'으로 막혔음."""
    from atlas.core.config import get_settings
    from atlas.ops import runs
    from atlas.walk import osm

    monkeypatch.setattr(get_settings(), "osm_dir", str(tmp_path))

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(osm, "_download", interrupt)
    with pytest.raises(KeyboardInterrupt):
        osm.refresh()
    assert runs.running_run("OSM_WALK") is None


def test_bad_calc_params_rejected_before_run(clean, engine):
    from atlas.calc.runner import create_calc_run

    with pytest.raises(Invalid):
        create_calc_run(params={"radiusKm": [1, 1.5]})
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM mart.calc_run")).scalar() == 0     # 실행 행이 생기지 않음
