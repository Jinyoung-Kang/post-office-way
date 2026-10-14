"""워커 — 작업 큐를 비우고, 스케줄 슬롯을 넣고, 끊긴 작업을 정리합니다 (`atlas worker`, compose 서비스 worker).

차선(lane)마다 스레드 하나: short(예보·공휴일·계산 등) / long(집계구·은행·도로·좌표 검증). 25분짜리 도로 거리 수집이
도는 동안에도 예보는 제시간에 갱신됩니다. 스케줄·정리(reap)는 따로 도는 스케줄 스레드 하나가 맡습니다
(차선이 긴 작업을 도는 동안에도 멈추지 않게, 한 번 실행·단일 차선 모드에서는 첫 차선이 맡음).
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
from atlas.core.jobctx import current_job_id
from atlas.core.config import get_settings
from atlas.ops import runs as collect_runs
from atlas.jobs import queue, registry, scheduler

log = logging.getLogger("atlas.worker")
HEARTBEAT_S = 30
REAP_EVERY_S = 60
SCHEDULE_TICK_S = 20.0    # 스케줄 스레드의 확인 주기 (슬롯 창 30분 안에서 충분히 촘촘)


def execute(job: dict[str, Any], worker: str | None = None, lane: str | None = None) -> bool:
    """작업 하나 실행 — 하트비트 스레드를 돌리고 결과를 기록. 성공하면 필요 시 지표 재계산을 이어서 넣음."""
    jid, kind = job["job_id"], job["kind"]
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(HEARTBEAT_S):
            try:
                queue.heartbeat(jid, worker=worker)
                if worker and lane:
                    queue.worker_beat(worker, lane, jid)
            except Exception:  # 하트비트 실패는 작업을 멈추지 않음 (DB 가 잠깐 끊겨도 reap 기준 10분)
                log.warning("heartbeat failed", extra={"jobId": jid})

    t = threading.Thread(target=beat, name=f"hb-{jid}", daemon=True)
    t.start()
    t0 = time.monotonic()
    log.info("job start", extra={"jobId": jid, "kind": kind, "attempt": job["attempts"]})
    ctx = current_job_id.set(jid)                 # 이 작업이 여는 실행 기록에 작업 id 를 남김 (reap 때 닫기, R1)
    try:
        spec = registry.get(kind)
        result = (run_isolated(kind, job["params"] or {}, jid, timeout_s=spec.timeout_s) if spec.isolate
                  else registry.run(kind, job["params"] or {}))
        # 수집기는 실패를 실행 기록(FAILED)에 남기고 정상 반환하기도 함 — 모두 실패면 작업도 실패, 재계산은 넣지 않음 (R6)
        if (ids := result.get("collectRunIds")) and set(collect_runs.statuses(ids)) == {"FAILED"}:
            raise RuntimeError(f"수집 실패 — 새 자료가 없어 재계산하지 않음 (collectRunIds={ids})")
        if spec.recalc and (job["params"] or {}).get("recalc", True):
            try:
                result["chainedCalcJobId"] = queue.enqueue("calc", source="chain", requested_by=f"job:{jid}")
            except queue.JobConflict as e:
                result["chainedCalcJobId"] = e.job_id    # 이미 '대기 중'인 계산이 이번 자료까지 반영 (실행 중이면 새로 들어감, V23)
        for nxt in spec.then:
            try:
                result.setdefault("chained", {})[nxt] = queue.enqueue(nxt, source="chain", requested_by=f"job:{jid}")
            except queue.JobConflict as e:
                result.setdefault("chained", {})[nxt] = e.job_id
        result["elapsedMs"] = int((time.monotonic() - t0) * 1000)
        queue.finish(jid, True, result, worker=worker)
        log.info("job done", extra={"jobId": jid, "kind": kind, "elapsedMs": result["elapsedMs"]})
        return True
    except Exception as e:  # 작업 실패는 기록만 하고 워커는 계속
        owned = queue.finish(jid, False, {"elapsedMs": int((time.monotonic() - t0) * 1000)},
                             error=f"{type(e).__name__}: {e}", worker=worker)
        try:   # 이 작업이 연 채 남은 실행 기록 — 격리 작업이 시간 초과·비정상 종료하면 자식의 정리 코드가 돌지 않음.
            # 작업을 아직 가진 경우만 — 정리(reap)된 뒤 다른 워커가 다시 가져갔으면 그 워커가 연 기록까지 닫게 됨(이때 내 기록은 reap 이 닫음)
            if owned and (n := queue.close_runs(jid, f"작업 실패로 닫음 — {type(e).__name__}")):
                log.warning("closed orphan runs", extra={"jobId": jid, "runs": n})
        except Exception:  # 정리 실패는 reap·다음 실행 판단에 맡김
            log.warning("close runs failed", extra={"jobId": jid})
        log.error("job failed", extra={"jobId": jid, "kind": kind, "error": str(e)[:300],
                                        "trace": traceback.format_exc(limit=3)})
        return False
    finally:
        current_job_id.reset(ctx)
        stop.set()


def _child(conn: Any, target: Any, kind: str, params: dict[str, Any], job_id: int | None) -> None:
    """자식 프로세스 본체 — 결과나 예외를 (종류, 메시지) 문자열로 부모에 보냄. 예외 객체를 그대로 보내면
    생성자 인자가 둘인 예외(RunInProgress·JobConflict)는 부모에서 되살리지 못해 원인이 BrokenProcessPool 로 가려졌음 (R9)."""
    from atlas.core.logging import setup_logging

    setup_logging()
    current_job_id.set(job_id)
    try:
        conn.send(("ok", (target or registry.run)(kind, params)))
    except BaseException as e:  # noqa: BLE001 — 자식의 모든 실패를 부모에 알림
        conn.send(("err", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def run_isolated(kind: str, params: dict[str, Any], job_id: int | None = None, timeout_s: float | None = None,
                 target: Any = None) -> dict[str, Any]:
    """새 프로세스(spawn)에서 작업 하나 — 파이썬은 쓴 메모리를 OS 에 잘 돌려주지 않아, 도보 그래프(수 GB)를
    워커 프로세스에서 돌리면 끝난 뒤에도 1GB 넘게 남았음. 자식 프로세스가 끝나면 모두 반환되고, 자식이 죽어도 워커는 남음.
    fork 대신 spawn — 워커의 스레드·DB 연결을 물려받지 않게.
    timeout_s 가 지나면 자식을 끝냄 — 예전에는 제한이 없고 하트비트는 계속 가서 멈춘 작업이 차선과 스케줄까지 막았음 (R5).
    target 은 테스트용 (기본: registry.run)."""
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_child, args=(send, target, kind, params, job_id), name=f"job-{kind}", daemon=True)
    p.start()
    send.close()
    try:
        if not recv.poll(timeout_s):
            raise TimeoutError(f"{kind} 작업이 {timeout_s:g}초 안에 끝나지 않아 중단했습니다")
        try:
            status, value = recv.recv()
        except EOFError as e:                       # 결과를 보내기 전에 자식이 죽음(메모리 부족 등)
            raise RuntimeError(f"{kind} 작업 프로세스가 비정상 종료했습니다 (exitcode={p.exitcode})") from e
    finally:
        recv.close()
        if p.is_alive():
            p.terminate()
        p.join(10)
    if status == "err":
        raise RuntimeError(value)
    return value


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
                if schedule:
                    last_reap = _schedule_tick(entries, last_reap)
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


def _schedule_tick(entries: list[scheduler.Entry], last_reap: float) -> float:
    """예정 슬롯 넣기 + (REAP_EVERY_S 마다) 끊긴 작업 정리. 마지막 정리 시각을 돌려줌."""
    for kind, slot in scheduler.due(now_kst(), entries):
        if registry.get(kind).missing():
            continue
        if jid := queue.try_enqueue_slot(kind, slot):
            log.info("scheduled", extra={"jobId": jid, "slot": slot})
    if time.monotonic() - last_reap > REAP_EVERY_S:
        if (r := queue.reap())["requeued"] or r["failed"]:
            log.warning("reaped stale jobs", extra=r)
        last_reap = time.monotonic()
    return last_reap


def run_scheduler(stop: threading.Event) -> None:
    """스케줄 슬롯 넣기·끊긴 작업 정리만 하는 스레드 — 차선이 긴 작업을 도는 동안에도 멈추지 않게.
    예전에는 short 차선 루프 안에서 작업 사이사이에만 확인해, short 작업이 30분 창을 넘기면 슬롯이 조용히 건너뛰어졌음 (R7)."""
    entries = scheduler.enabled(get_settings().atlas_schedule)
    log.info("scheduler start", extra={"schedule": [e.kind for e in entries]})
    last_reap, backoff = 0.0, 0.0
    while not stop.is_set():
        try:
            last_reap = _schedule_tick(entries, last_reap)
            backoff = 0.0
        except _DB_DOWN as e:
            backoff = min(backoff * 2 or 1.0, RETRY_MAX_S)
            log.warning("scheduler: db unavailable — retrying", extra={"retryInS": backoff,
                                                                       "error": str(e).splitlines()[0][:200]})
        except Exception:  # noqa: BLE001 — 한 번의 예상 밖 오류로 스레드가 죽으면 워커 전체가 재시작을 반복함
            backoff = min(backoff * 2 or 1.0, RETRY_MAX_S)
            log.exception("scheduler tick failed — retrying", extra={"retryInS": backoff})
        stop.wait(backoff or SCHEDULE_TICK_S)


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
                                kwargs={"lane": lane, "poll_s": poll_s, "stop": stopping, "schedule": False})
               for lane in lanes]
    threads.append(threading.Thread(target=run_scheduler, name="scheduler", daemon=True, args=(stopping,)))
    for t in threads:
        t.start()
    while not stopping.wait(1.0):
        if not all(t.is_alive() for t in threads):     # DB 끊김은 차선이 스스로 복구 — 그 밖의 예외로 죽으면 전체 종료 → compose 가 재시작
            log.error("worker lane died — exiting for restart")
            stopping.set()
    for t in threads:
        t.join(timeout=65)
