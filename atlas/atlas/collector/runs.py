"""ops.collect_run 기록 — 모든 원본·품질 이슈가 run 에 묶입니다."""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from atlas.core.db import begin

# RUNNING 인 채로 이 시간이 지나면 죽은 실행으로 보고 새 실행을 막지 않습니다.
STALE_HOURS = 6


class RunInProgress(RuntimeError):
    def __init__(self, kind: str, run_id: str):
        super().__init__(f"{kind} 수집이 이미 실행 중입니다 (collectRunId={run_id})")
        self.kind, self.run_id = kind, run_id


def running_run(kind: str) -> str | None:
    with begin() as c:
        r = c.execute(text("""SELECT collect_run_id FROM ops.collect_run
                              WHERE kind = :k AND status = 'RUNNING'
                                AND started_at > now() - make_interval(hours => :h)
                              ORDER BY started_at DESC LIMIT 1"""), {"k": kind, "h": STALE_HOURS}).first()
    return str(r[0]) if r else None


def start_run(kind: str, scope: str | None = None, check_running: bool = True) -> uuid.UUID:
    if check_running and (rid := running_run(kind)):
        raise RunInProgress(kind, rid)
    with begin() as c:
        rid = c.execute(text("""INSERT INTO ops.collect_run (kind, status, scope, stats)
                                VALUES (:k, 'RUNNING', :s, '{}'::jsonb) RETURNING collect_run_id"""),
                        {"k": kind, "s": scope}).scalar_one()
    return rid


def reopen_run(run_id: uuid.UUID, kind: str) -> dict[str, Any]:
    """중단된 run 을 RUNNING 으로 되돌리고 기존 stats 를 돌려줍니다 (FR-105 재개).

    같은 종류의 가장 최근 실행이고 PARTIAL·FAILED 일 때만 — 오래된 실행을 다시 열면 그 뒤 수집된 자료를
    낡은 스냅샷으로 되돌리게 되고(스냅샷이 정리됐으면 성공 코드의 시설이 모두 닫힘), 다른 종류의 실행 행을 덮어씀.
    """
    with begin() as c:
        r = c.execute(text("""SELECT kind, status, started_at FROM ops.collect_run WHERE collect_run_id = :id
                              FOR UPDATE"""), {"id": run_id}).first()
        if not r:
            raise ValueError(f"collect_run {run_id} 가 없습니다.")
        if r.kind != kind:
            raise ValueError(f"재개할 수 없습니다: 수집 종류가 다릅니다 ({r.kind} ≠ {kind}).")
        if r.status not in ("PARTIAL", "FAILED"):
            raise ValueError(f"재개할 수 없습니다: 상태가 {r.status} 입니다 (PARTIAL·FAILED 만 이어 받기).")
        newer = c.execute(text("""SELECT 1 FROM ops.collect_run WHERE kind = :k AND started_at > :t LIMIT 1"""),
                          {"k": kind, "t": r.started_at}).first()
        if newer:
            raise ValueError("재개할 수 없습니다: 같은 종류의 더 최근 실행이 있습니다 — 새로 수집하세요.")
        st = c.execute(text("""UPDATE ops.collect_run SET status = 'RUNNING', finished_at = NULL, error = NULL
                               WHERE collect_run_id = :id RETURNING stats, scope"""), {"id": run_id}).first()
    return {"kind": kind, "stats": st[0] or {}, "scope": st[1]}


def save_stats(run_id: uuid.UUID, stats: dict[str, Any]) -> None:
    with begin() as c:
        c.execute(text("UPDATE ops.collect_run SET stats = CAST(:s AS jsonb) WHERE collect_run_id = :id"),
                  {"s": json.dumps(stats, ensure_ascii=False), "id": run_id})


def finish_run(run_id: uuid.UUID, status: str, stats: dict[str, Any], error: str | None = None) -> None:
    with begin() as c:
        c.execute(text("""UPDATE ops.collect_run SET status = :st, stats = CAST(:s AS jsonb),
                                 error = :e, finished_at = now() WHERE collect_run_id = :id"""),
                  {"st": status, "s": json.dumps(stats, ensure_ascii=False), "e": error, "id": run_id})
