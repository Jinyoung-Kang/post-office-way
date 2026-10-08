"""지금 실행 중인 작업 id — 워커가 작업을 돌리는 동안 설정하고, 실행 기록(collect_run·calc_run·walk_run)을 만들 때 남김.
워커가 죽어 작업을 정리(reap)할 때 그 작업의 실행 기록을 찾아 닫는 데 씀 (V22). 차선마다 스레드라 ContextVar."""
from __future__ import annotations

from contextvars import ContextVar

current_job_id: ContextVar[int | None] = ContextVar("current_job_id", default=None)
