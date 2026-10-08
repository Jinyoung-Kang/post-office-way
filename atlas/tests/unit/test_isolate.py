"""격리 작업(자식 프로세스) — 시간 제한(R5)과 예외 전달(R9). DB 없이."""
import time

import pytest

from atlas.jobs import worker
from tests.unit import isolate_targets as t


def test_isolated_job_is_killed_after_timeout():
    t0 = time.monotonic()
    with pytest.raises(TimeoutError, match="1초"):
        worker.run_isolated("sleepy", {"s": 30}, timeout_s=1, target=t.sleepy)
    assert time.monotonic() - t0 < 15                             # 30초를 기다리지 않음


def test_isolated_job_result_and_unpicklable_error():
    assert worker.run_isolated("sleepy", {"s": 0}, target=t.sleepy) == {"slept": 0}
    with pytest.raises(RuntimeError, match="TwoArgError: two-arg 실행 중"):
        worker.run_isolated("two-arg", {}, target=t.two_arg_error)  # 예전에는 BrokenProcessPool 로 원인이 가려짐


def test_worker_db_statement_timeout_option():
    from atlas.core.db import engine_options

    assert engine_options(0) == {}
    assert engine_options(1_800_000) == {"options": "-c statement_timeout=1800000"}

