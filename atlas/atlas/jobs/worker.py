"""워커 — 작업 큐를 비우고, 스케줄 슬롯을 넣고, 끊긴 작업을 정리합니다 (`atlas worker`, compose 서비스 worker).

차선(lane)마다 스레드 하나: short(예보·공휴일·계산 등) / long(집계구·은행·도로·좌표 검증). 25분짜리 도로 거리 수집이
도는 동안에도 예보는 제시간에 갱신됩니다. 스케줄·정리(reap)는 short 차선만 맡아 중복되지 않게 합니다.
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
import sqlalchemy.exc

from atlas.core.clock import now_kst
from atlas.core.config import get_settings
from atlas.jobs import queue, registry, scheduler

log = logging.getLogger("atlas.worker")
HEARTBEAT_S = 30
REAP_EVERY_S = 60


def execute(job: dict[str, Any], worker: str | None = None, lane: str | None = None) -> bool:
    """작업 하나 실행 — 하트비트 스레드를 돌리고 결과를 기록. 성공하면 필요 시 지표 재계산을 이어서 넣음."""
    jid, kind = job["job_id"], job["kind"]
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(HEARTBEAT_S):
            try:
                queue.heartbeat(jid)
                if worker and lane:
                    queue.worker_beat(worker, lane, jid)
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


# DB 가 잠깐 끊기거나(재시작·장애 복구) 아직 준비되지 않았을 때 나는 오류 — 차선을 죽이지 않고 다시 연결
_DB_DOWN = (psycopg.OperationalError, sqlalchemy.exc.OperationalError, sqlalchemy.exc.InterfaceError)
RETRY_MAX_S = 30


def run_lane(lane: str, poll_s: float = 30.0, once: bool = False, stop: threading.Event | None = None,
             schedule: bool = True) -> None:
    """한 차선의 작업만 가져가는 루프. schedule=True 인 차선이 스케줄 슬롯 넣기와 끊긴 작업 정리를 맡음.

    DB 연결이 끊기면 1·2·4…최대 30초 간격으로 다시 연결합니다. 실행 중이던 작업은 하트비트가 끊겨 reap 가 다시 대기열로 돌립니다.
    """
    s = get_settings()
    name = f"{queue.worker_name()}/{lane}"
    kinds = registry.kinds_for(lane)
    entries = scheduler.enabled(s.atlas_schedule) if schedule else []
    stopping = stop or threading.Event()
    log.info("worker lane start", extra={"worker": name, "lane": lane, "kinds": kinds,
                                          "schedule": [e.kind for e in entries]})
    listen: psycopg.Connection | None = None
    last_reap = 0.0
    backoff = 0.0
    try:
        while not stopping.is_set():
            try:
                if listen is None:
                    listen = _listen_conn()
                queue.worker_beat(name, lane)
                if backoff:
                    log.info("db reconnected", extra={"worker": name})
                    backoff = 0.0
                for kind, slot in scheduler.due(now_kst(), entries):
                    if registry.get(kind).missing():
                        continue
                    if jid := queue.try_enqueue_slot(kind, slot):
                        log.info("scheduled", extra={"jobId": jid, "slot": slot})
                if schedule and time.monotonic() - last_reap > REAP_EVERY_S:
                    if (r := queue.reap())["requeued"] or r["failed"]:
                        log.warning("reaped stale jobs", extra=r)
                    last_reap = time.monotonic()
                job = queue.claim(name, kinds)
                if job:
                    queue.worker_beat(name, lane, job["job_id"])
                    execute(job, name, lane)
                    continue
                if once:
                    break
                # 알림이 오거나 poll_s 가 지나면 깨어남 (스케줄 확인·생존 신호 주기 겸용)
                for _ in listen.notifies(timeout=poll_s, stop_after=1):
                    pass
            except _DB_DOWN as e:
                backoff = min(backoff * 2 or 1.0, RETRY_MAX_S)
                log.warning("db unavailable — retrying", extra={"worker": name, "retryInS": backoff,
                                                                "error": str(e).splitlines()[0][:200]})
                if listen is not None:
                    try:
                        listen.close()
                    except Exception:  # 이미 끊긴 연결
                        pass
                    listen = None
                if once:
                    raise
                stopping.wait(backoff)
    finally:
        if listen is not None:
            listen.close()
        try:
            queue.worker_gone(name)
        except Exception:  # 종료 중 DB 가 먼저 내려가도 워커는 끝냄
            pass
        log.info("worker lane stop", extra={"worker": name})


def run_forever(poll_s: float = 30.0, once: bool = False, stop: threading.Event | None = None,
                lanes: tuple[str, ...] = registry.LANES) -> None:
    stopping = stop or threading.Event()
    if stop is None:          # 메인 스레드에서만 시그널을 받을 수 있음 (테스트는 stop 이벤트로 멈춤)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopping.set())
    if once or len(lanes) == 1:
        for i, lane in enumerate(lanes):
            run_lane(lane, poll_s, once, stopping, schedule=(i == 0))
        return
    threads = [threading.Thread(target=run_lane, name=f"lane-{lane}", daemon=True,
                                kwargs={"lane": lane, "poll_s": poll_s, "stop": stopping, "schedule": lane == lanes[0]})
               for lane in lanes]
    for t in threads:
        t.start()
    while not stopping.wait(1.0):
        if not all(t.is_alive() for t in threads):     # DB 끊김은 차선이 스스로 복구 — 그 밖의 예외로 죽으면 전체 종료 → compose 가 재시작
            log.error("worker lane died — exiting for restart")
            stopping.set()
    for t in threads:
        t.join(timeout=65)
