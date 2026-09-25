"""워커 — 작업 큐를 비우고, 스케줄 슬롯을 넣고, 끊긴 작업을 정리합니다 (`atlas worker`, compose 서비스 worker).

대기 중에는 LISTEN atlas_jobs 로 잠들어 있다가 API 가 작업을 넣으면(NOTIFY) 바로 깨어납니다.
SIGTERM 을 받으면 새 작업을 가져가지 않고, 실행 중인 작업이 끝나면 종료합니다.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
import traceback
from typing import Any

import psycopg

from atlas.core.clock import now_kst
from atlas.core.config import get_settings
from atlas.jobs import queue, registry, scheduler

log = logging.getLogger("atlas.worker")
HEARTBEAT_S = 30
REAP_EVERY_S = 60


def execute(job: dict[str, Any]) -> bool:
    """작업 하나 실행 — 하트비트 스레드를 돌리고 결과를 기록. 성공하면 필요 시 지표 재계산을 이어서 넣음."""
    jid, kind = job["job_id"], job["kind"]
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(HEARTBEAT_S):
            try:
                queue.heartbeat(jid)
            except Exception:  # 하트비트 실패는 작업을 멈추지 않음 (DB 가 잠깐 끊겨도 reap 기준 10분)
                log.warning("heartbeat failed", extra={"jobId": jid})

    t = threading.Thread(target=beat, name=f"hb-{jid}", daemon=True)
    t.start()
    t0 = time.monotonic()
    log.info("job start", extra={"jobId": jid, "kind": kind, "attempt": job["attempts"]})
    try:
        spec = registry.get(kind)
        result = registry.run(kind, job["params"] or {})
        if spec.recalc and (job["params"] or {}).get("recalc", True):
            try:
                result["chainedCalcJobId"] = queue.enqueue("calc", source="chain", requested_by=f"job:{jid}")
            except queue.JobConflict as e:
                result["chainedCalcJobId"] = e.job_id    # 이미 대기 중인 계산이 이번 자료까지 반영
        result["elapsedMs"] = int((time.monotonic() - t0) * 1000)
        queue.finish(jid, True, result)
        log.info("job done", extra={"jobId": jid, "kind": kind, "elapsedMs": result["elapsedMs"]})
        return True
    except Exception as e:  # 작업 실패는 기록만 하고 워커는 계속
        queue.finish(jid, False, {"elapsedMs": int((time.monotonic() - t0) * 1000)},
                     error=f"{type(e).__name__}: {e}")
        log.error("job failed", extra={"jobId": jid, "kind": kind, "error": str(e)[:300],
                                        "trace": traceback.format_exc(limit=3)})
        return False
    finally:
        stop.set()


def _listen_conn() -> psycopg.Connection:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(url, autocommit=True)
    conn.execute(f"LISTEN {queue.CHANNEL}")
    return conn


def run_forever(poll_s: float = 30.0, once: bool = False, stop: threading.Event | None = None) -> None:
    s = get_settings()
    name = queue.worker_name()
    entries = scheduler.enabled(s.atlas_schedule)
    stopping = stop or threading.Event()
    if stop is None:          # 메인 스레드에서만 시그널을 받을 수 있음 (테스트는 stop 이벤트로 멈춤)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopping.set())
    log.info("worker start", extra={"worker": name, "schedule": [e.kind for e in entries]})
    listen = _listen_conn()
    last_reap = 0.0
    try:
        while not stopping.is_set():
            for kind, slot in scheduler.due(now_kst(), entries):
                if registry.get(kind).missing():
                    continue
                if jid := queue.try_enqueue_slot(kind, slot):
                    log.info("scheduled", extra={"jobId": jid, "slot": slot})
            if time.monotonic() - last_reap > REAP_EVERY_S:
                if (r := queue.reap())["requeued"] or r["failed"]:
                    log.warning("reaped stale jobs", extra=r)
                last_reap = time.monotonic()
            job = queue.claim(name)
            if job:
                execute(job)
                continue
            if once:
                break
            # 알림이 오거나 poll_s 가 지나면 깨어남 (스케줄 확인 주기 겸용)
            for _ in listen.notifies(timeout=poll_s, stop_after=1):
                pass
    finally:
        listen.close()
        log.info("worker stop", extra={"worker": name})
