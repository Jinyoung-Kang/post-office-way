"""Postgres 작업 큐 (ops.job) — 별도 브로커 없이 트랜잭션·잠금으로 '정확히 한 워커'를 보장합니다.

- enqueue : INSERT (같은 종류가 대기·실행 중이면 ux_job_active 로 막힘 → JobConflict) + NOTIFY 로 워커 즉시 깨움
- claim   : SELECT … FOR UPDATE SKIP LOCKED — 워커가 여럿이어도 한 작업은 한 워커만 가져감
- heartbeat / reap : 실행 중 주기적으로 heartbeat_at 갱신, 끊긴 작업(워커 종료)은 재시도 또는 FAILED
"""
from __future__ import annotations

import json
import socket
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from atlas.core.db import get_engine

CHANNEL = "atlas_jobs"
STALE_MIN = 10          # 하트비트가 이만큼 끊기면 워커가 죽은 것으로 봄


class JobConflict(RuntimeError):
    def __init__(self, kind: str, job_id: int | None):
        super().__init__(f"{kind} 작업이 이미 대기·실행 중입니다 (jobId={job_id})")
        self.kind, self.job_id = kind, job_id


def worker_name() -> str:
    import os

    return f"{socket.gethostname()}:{os.getpid()}"


def active(kind: str, engine: Engine | None = None) -> int | None:
    with (engine or get_engine()).connect() as c:
        return c.execute(text("SELECT job_id FROM ops.job WHERE kind = :k AND status IN ('QUEUED', 'RUNNING')"),
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
    """가장 오래 기다린 작업 하나 — kinds 를 주면 그 종류만(차선별 워커)."""
    with (engine or get_engine()).begin() as c:
        r = c.execute(text("""
            UPDATE ops.job SET status = 'RUNNING', started_at = now(), heartbeat_at = now(),
                               attempts = attempts + 1, worker = :w, error = NULL
             WHERE job_id = (SELECT job_id FROM ops.job WHERE status = 'QUEUED'
                               AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
                              ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1)
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


def heartbeat(job_id: int, engine: Engine | None = None) -> None:
    with (engine or get_engine()).begin() as c:
        c.execute(text("UPDATE ops.job SET heartbeat_at = now() WHERE job_id = :id AND status = 'RUNNING'"),
                  {"id": job_id})


def finish(job_id: int, ok: bool, result: dict[str, Any] | None = None, error: str | None = None,
           engine: Engine | None = None) -> None:
    with (engine or get_engine()).begin() as c:
        c.execute(text("""UPDATE ops.job SET status = :st, result = CAST(:r AS jsonb), error = :e, finished_at = now()
                          WHERE job_id = :id"""),
                  {"st": "DONE" if ok else "FAILED", "r": json.dumps(result or {}, default=str),
                   "e": (error or "")[:2000] or None, "id": job_id})


def reap(engine: Engine | None = None) -> dict[str, int]:
    """하트비트가 끊긴 RUNNING 작업 — 시도 횟수가 남았으면 다시 대기열로, 아니면 FAILED."""
    with (engine or get_engine()).begin() as c:
        requeued = c.execute(text(f"""
            UPDATE ops.job SET status = 'QUEUED', worker = NULL, error = '워커 응답 없음 — 다시 대기열로'
             WHERE status = 'RUNNING' AND heartbeat_at < now() - interval '{STALE_MIN} minutes'
               AND attempts < max_attempts""")).rowcount
        failed = c.execute(text(f"""
            UPDATE ops.job SET status = 'FAILED', finished_at = now(), error = '워커 응답 없음 — 재시도 횟수 초과'
             WHERE status = 'RUNNING' AND heartbeat_at < now() - interval '{STALE_MIN} minutes'""")).rowcount
        c.execute(text("DELETE FROM ops.worker WHERE last_seen < now() - interval '1 day'"))   # 꺼진 워커 흔적
    return {"requeued": requeued, "failed": failed}


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
