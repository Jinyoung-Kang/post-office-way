"""Postgres 작업 큐 (ops.job) — 별도 브로커 없이 트랜잭션·잠금으로 '정확히 한 워커'를 보장합니다.

- enqueue : INSERT (같은 종류가 대기 중이면 ux_job_queued 로 막힘 → JobConflict) + NOTIFY 로 워커 즉시 깨움.
            실행 중인 같은 종류가 있으면 새로 대기열에 들어가 그것이 끝난 뒤 실행 (V23)
- claim   : SELECT … FOR UPDATE SKIP LOCKED — 워커가 여럿이어도 한 작업은 한 워커만 가져감
- heartbeat / reap : 실행 중 주기적으로 heartbeat_at 갱신, 끊긴 작업(워커 종료)은 재시도 또는 FAILED
"""
from __future__ import annotations

import json
import logging
import socket
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from atlas.core.db import get_engine
from atlas.core.masking import safe_error

CHANNEL = "atlas_jobs"
log = logging.getLogger(__name__)
STALE_MIN = 10          # 하트비트가 이만큼 끊기면 워커가 죽은 것으로 봄


class JobConflict(RuntimeError):
    def __init__(self, kind: str, job_id: int | None):
        super().__init__(f"{kind} 작업이 이미 대기 중입니다 (jobId={job_id})")
        self.kind, self.job_id = kind, job_id


def worker_name() -> str:
    import os

    return f"{socket.gethostname()}:{os.getpid()}"


def active(kind: str, engine: Engine | None = None) -> int | None:
    """같은 종류의 대기 중 작업 (대기 중은 하나만 — V23)."""
    with (engine or get_engine()).connect() as c:
        return c.execute(text("SELECT job_id FROM ops.job WHERE kind = :k AND status = 'QUEUED'"),
                         {"k": kind}).scalar()


def enqueue(kind: str, params: dict[str, Any] | None = None, *, source: str = "api", requested_by: str | None = None,
            slot: str | None = None, engine: Engine | None = None) -> int:
    eng = engine or get_engine()
    try:
        with eng.begin() as c:
            jid = c.execute(text("""INSERT INTO ops.job (kind, params, source, requested_by, slot)
                                    VALUES (:k, CAST(:p AS jsonb), :src, :by, :slot) RETURNING job_id"""),
                            {"k": kind, "p": json.dumps(params or {}), "src": source, "by": requested_by,
                             "slot": slot}).scalar_one()
            c.execute(text("SELECT pg_notify(:ch, :id)"), {"ch": CHANNEL, "id": str(jid)})
            return jid
    except IntegrityError as e:
        raise JobConflict(kind, active(kind, eng)) from e


def try_enqueue_slot(kind: str, slot: str, params: dict[str, Any] | None = None,
                     engine: Engine | None = None) -> int | None:
    """스케줄용 — 이미 같은 슬롯이 있거나 같은 종류가 대기·실행 중이면 조용히 건너뜀(None)."""
    with (engine or get_engine()).begin() as c:
        jid = c.execute(text("""INSERT INTO ops.job (kind, params, source, slot)
                                VALUES (:k, CAST(:p AS jsonb), 'schedule', :slot)
                                ON CONFLICT DO NOTHING RETURNING job_id"""),
                        {"k": kind, "p": json.dumps(params or {}), "slot": slot}).scalar()
        if jid:
            c.execute(text("SELECT pg_notify(:ch, :id)"), {"ch": CHANNEL, "id": str(jid)})
        return jid


def claim(worker: str, kinds: list[str] | None = None, engine: Engine | None = None) -> dict[str, Any] | None:
    """가장 오래 기다린 작업 하나 — kinds 를 주면 그 종류만(차선별 워커).
    같은 종류가 실행 중이면 건너뜀(대기 중인 것은 실행 중인 것이 끝난 뒤에 — 같은 종류가 동시에 두 개 돌지 않게, V23)."""
    with (engine or get_engine()).begin() as c:
        r = c.execute(text("""
            UPDATE ops.job SET status = 'RUNNING', started_at = now(), heartbeat_at = now(),
                               attempts = attempts + 1, worker = :w, error = NULL
             WHERE job_id = (SELECT q.job_id FROM ops.job q WHERE q.status = 'QUEUED'
                               AND (CAST(:kinds AS text[]) IS NULL OR q.kind = ANY(CAST(:kinds AS text[])))
                               AND NOT EXISTS (SELECT 1 FROM ops.job r WHERE r.kind = q.kind AND r.status = 'RUNNING')
                              ORDER BY q.created_at, q.job_id FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING job_id, kind, params, source, attempts, max_attempts"""),
            {"w": worker, "kinds": kinds}).mappings().first()
    return dict(r) if r else None


def worker_beat(worker: str, lane: str, job_id: int | None = None, engine: Engine | None = None) -> None:
    """워커 생존 신호 (ops.worker) — 실행 중 작업이 있으면 함께 기록."""
    with (engine or get_engine()).begin() as c:
        c.execute(text("""INSERT INTO ops.worker (worker, lane, job_id) VALUES (:w, :l, :j)
                          ON CONFLICT (worker) DO UPDATE SET last_seen = now(), job_id = EXCLUDED.job_id"""),
                  {"w": worker, "l": lane, "j": job_id})


def worker_gone(worker: str, engine: Engine | None = None) -> None:
    with (engine or get_engine()).begin() as c:
        c.execute(text("DELETE FROM ops.worker WHERE worker = :w"), {"w": worker})


def workers(engine: Engine | None = None, alive_s: int = 120) -> list[dict[str, Any]]:
    """최근 alive_s 초 안에 신호를 보낸 워커."""
    # 읽기 전용 — API(atlas_api 역할, DELETE 권한 없음)도 부름. 오래된 행 정리는 워커의 reap() 가 함
    with (engine or get_engine()).connect() as c:
        return [dict(r) for r in c.execute(text("""
            SELECT worker, lane, job_id, round(extract(epoch FROM now() - last_seen)) AS seen_s,
                   round(extract(epoch FROM now() - started_at)) AS up_s
              FROM ops.worker WHERE last_seen > now() - make_interval(secs => :a) ORDER BY lane, worker"""),
            {"a": alive_s}).mappings()]


# worker 를 주면 그 워커가 가진(RUNNING) 작업일 때만 — 정리(reap)된 뒤 다른 워커가 다시 가져간 작업을 처음 워커가
# 늦게 끝내거나 하트비트를 보내 덮어쓰지 않게 (R8). worker 없이 부르면(관리·테스트) 상태만 확인
_OWNED = "job_id = :id AND status = 'RUNNING' AND (CAST(:w AS text) IS NULL OR worker = CAST(:w AS text))"


def heartbeat(job_id: int, engine: Engine | None = None, worker: str | None = None) -> None:
    with (engine or get_engine()).begin() as c:
        c.execute(text(f"UPDATE ops.job SET heartbeat_at = now() WHERE {_OWNED}"), {"id": job_id, "w": worker})


def finish(job_id: int, ok: bool, result: dict[str, Any] | None = None, error: str | None = None,
           engine: Engine | None = None, worker: str | None = None) -> bool:
    """작업 결과 기록. 이미 다른 워커에게 넘어갔으면 기록하지 않고 False."""
    with (engine or get_engine()).begin() as c:
        n = c.execute(text(f"""UPDATE ops.job SET status = :st, result = CAST(:r AS jsonb), error = :e, finished_at = now()
                               WHERE {_OWNED}"""),
                      {"st": "DONE" if ok else "FAILED", "r": json.dumps(result or {}, default=str),
                       "e": safe_error(error) or None, "id": job_id, "w": worker}).rowcount
    if not n:
        log.warning("job finish ignored — no longer owned", extra={"jobId": job_id, "worker": worker})
    return bool(n)


def _close_runs(c: Any, job_ids: list[int], reason: str) -> int:
    """작업이 연 채 남은 실행 기록(수집·계산·도보)을 FAILED 로 — 남으면 다음 실행이 '이미 실행 중'으로 막힘."""
    n = 0
    for table in ("ops.collect_run", "mart.calc_run", "mart.walk_run"):
        n += c.execute(text(f"""UPDATE {table} SET status = 'FAILED', finished_at = now(), error = :e
                                 WHERE status = 'RUNNING' AND job_id = ANY(CAST(:ids AS bigint[]))"""),
                       {"ids": job_ids, "e": reason}).rowcount
    return n


def close_runs(job_id: int, reason: str, engine: Engine | None = None) -> int:
    """끝난(실패한) 작업의 RUNNING 실행 기록을 닫음 — 격리 작업이 시간 초과·비정상 종료로 끝나면 자식의 정리 코드가 돌지 않음."""
    with (engine or get_engine()).begin() as c:
        return _close_runs(c, [job_id], reason)


def reap(engine: Engine | None = None) -> dict[str, int]:
    """하트비트가 끊긴 RUNNING 작업 — 시도 횟수가 남았으면 다시 대기열로, 아니면 FAILED.
    그 작업이 연 실행 기록(수집·계산·도보)도 FAILED 로 닫음 — 남으면 재시도가 '이미 실행 중'으로 실패 (R1)."""
    stale = f"j.status = 'RUNNING' AND j.heartbeat_at < now() - interval '{STALE_MIN} minutes'"
    try:
        return _reap(engine, stale)
    except IntegrityError:   # 두 UPDATE 사이에 같은 종류가 대기열에 들어옴(V23) — 이 주기는 되돌리고 다음 주기에 '대신함'으로 처리
        log.warning("reap skipped — same kind enqueued concurrently")
        return {"requeued": 0, "failed": 0}


def _reap(engine: Engine | None, stale: str) -> dict[str, int]:
    with (engine or get_engine()).begin() as c:
        # 같은 종류가 이미 대기 중이면 그 작업이 대신함 — 다시 넣으면 '대기 중 하나' 고유 인덱스(V23) 위반으로 정리 전체가 실패했음
        superseded = [r[0] for r in c.execute(text(f"""
            UPDATE ops.job j SET status = 'FAILED', finished_at = now(),
                                 error = '워커 응답 없음 — 같은 종류가 이미 대기 중이라 그 작업이 대신함'
             WHERE {stale} AND EXISTS (SELECT 1 FROM ops.job q WHERE q.kind = j.kind AND q.status = 'QUEUED')
            RETURNING job_id"""))]
        requeued = [r[0] for r in c.execute(text(f"""
            UPDATE ops.job j SET status = 'QUEUED', worker = NULL, error = '워커 응답 없음 — 다시 대기열로'
             WHERE {stale} AND j.attempts < j.max_attempts RETURNING job_id"""))]
        failed = superseded + [r[0] for r in c.execute(text(f"""
            UPDATE ops.job j SET status = 'FAILED', finished_at = now(), error = '워커 응답 없음 — 재시도 횟수 초과'
             WHERE {stale} RETURNING job_id"""))]
        if ids := requeued + failed:
            _close_runs(c, ids, "워커 응답 없음 — 작업이 중단되어 닫음")
        c.execute(text("DELETE FROM ops.worker WHERE last_seen < now() - interval '1 day'"))   # 꺼진 워커 흔적
    return {"requeued": len(requeued), "failed": len(failed)}


def cancel(job_id: int, engine: Engine | None = None) -> bool:
    with (engine or get_engine()).begin() as c:
        return bool(c.execute(text("""UPDATE ops.job SET status = 'CANCELLED', finished_at = now()
                                       WHERE job_id = :id AND status = 'QUEUED'"""), {"id": job_id}).rowcount)


def recent(limit: int = 30, with_requester: bool = False, engine: Engine | None = None) -> list[dict[str, Any]]:
    """최근 작업. 요청 IP(requested_by)는 관리자 목록에서만."""
    extra = ", requested_by" if with_requester else ""
    with (engine or get_engine()).connect() as c:
        return [dict(r) for r in c.execute(text(f"""
            SELECT job_id, kind, status, source, slot, attempts, worker, result, error,
                   created_at, started_at, heartbeat_at, finished_at{extra}
              FROM ops.job ORDER BY created_at DESC, job_id DESC LIMIT :n"""), {"n": limit}).mappings()]
