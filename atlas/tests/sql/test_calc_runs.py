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
