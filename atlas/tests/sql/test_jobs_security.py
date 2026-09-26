"""작업 큐(ops.job)·워커·관리 API, 최소 권한 역할(atlas_api), 보안 헤더·ETag·속도 제한 — PostGIS 테스트 DB.

작업 실행 함수는 가짜로 바꿔 수집 API 를 부르지 않습니다.
"""
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.jobs import queue, registry, worker
from atlas.jobs.registry import JobSpec

pytestmark = pytest.mark.db


@pytest.fixture()
def fake_jobs(monkeypatch, clean):
    ran = []

    def ok(p):
        ran.append(("ok", p))
        return {"collectRunIds": []}

    def boom(_):
        raise RuntimeError("수집 실패")

    jobs = {**registry.JOBS,
            "okjob": JobSpec("okjob", "테스트", ok, recalc=True),
            "boom": JobSpec("boom", "실패", boom),
            "calc": JobSpec("calc", "지표 계산", lambda p: ran.append(("calc", p)) or {"calcRunId": "x"})}
    monkeypatch.setattr(registry, "JOBS", jobs)
    return ran


def test_enqueue_claim_finish_and_chain(fake_jobs, engine):
    jid = queue.enqueue("okjob", {"a": 1}, requested_by="127.0.0.1")
    with pytest.raises(queue.JobConflict):                       # 같은 종류는 대기·실행 중 하나만
        queue.enqueue("okjob")
    job = queue.claim("w1")
    assert job["job_id"] == jid and job["attempts"] == 1 and queue.claim("w2") is None   # SKIP LOCKED
    assert worker.execute(job)
    rows = {r["job_id"]: r for r in queue.recent()}
    assert rows[jid]["status"] == "DONE" and rows[jid]["result"]["chainedCalcJobId"]
    calc = queue.claim("w1")                                     # 재계산이 이어서 들어감
    assert calc["kind"] == "calc" and calc["source"] == "chain"
    worker.execute(calc)
    assert [k for k, _ in fake_jobs] == ["ok", "calc"]


def test_failure_is_recorded(fake_jobs):
    queue.enqueue("boom")
    job = queue.claim("w1")
    assert not worker.execute(job)
    r = queue.recent(1)[0]
    assert r["status"] == "FAILED" and "수집 실패" in r["error"]


def test_schedule_slot_once_and_reap(fake_jobs, engine):
    assert queue.try_enqueue_slot("okjob", "okjob@2026-09-25T05:20")
    assert queue.try_enqueue_slot("okjob", "okjob@2026-09-25T05:20") is None       # 같은 슬롯
    queue.claim("dead-worker")
    with engine.begin() as c:
        c.execute(text("UPDATE ops.job SET heartbeat_at = now() - interval '20 minutes'"))
    assert queue.reap() == {"requeued": 1, "failed": 0}
    queue.claim("w2")
    with engine.begin() as c:
        c.execute(text("UPDATE ops.job SET heartbeat_at = now() - interval '20 minutes'"))
    assert queue.reap() == {"requeued": 0, "failed": 1}                             # 재시도 2회 초과


def test_worker_wakes_on_notify(fake_jobs, monkeypatch, engine):
    """대기열이 비었을 때 LISTEN 으로 잠들어 있다가 NOTIFY 로 깨어나 작업을 처리."""
    from atlas.core.config import get_settings

    monkeypatch.setattr(get_settings(), "atlas_schedule", "")        # 테스트 중 실제 예보 작업이 들어가지 않게
    done, stop = threading.Event(), threading.Event()
    orig = worker.execute

    def spy(job, *a, **kw):
        r = orig(job, *a, **kw)
        done.set()
        return r

    monkeypatch.setattr(worker, "execute", spy)
    t = threading.Thread(target=worker.run_forever, kwargs={"poll_s": 5.0, "stop": stop}, daemon=True)
    t.start()
    import time

    time.sleep(0.5)
    queue.enqueue("okjob", {"recalc": False})
    try:
        assert done.wait(3), "NOTIFY 뒤 3초 안에 처리돼야 함 (폴링 5초보다 빠름)"
    finally:
        stop.set()
        with engine.begin() as c:                                      # 잠든 워커를 깨워 종료
            c.execute(text("SELECT pg_notify('atlas_jobs', 'stop')"))
        t.join(6)
    assert not t.is_alive()


@pytest.fixture()
def client(fake_jobs, monkeypatch):
    from atlas.core import config

    monkeypatch.setattr(config.get_settings(), "admin_token", "t" * 32)
    from atlas.api.main import app

    with TestClient(app) as c:
        yield c


def test_admin_api_enqueues(client):
    assert client.post("/api/v1/admin/jobs", json={"kind": "okjob"}).status_code == 401
    assert client.post("/api/v1/admin/jobs", json={"kind": "okjob"}, headers={"X-Admin-Token": "x" * 32}).status_code == 401
    h = {"X-Admin-Token": "t" * 32}
    r = client.post("/api/v1/admin/jobs", json={"kind": "okjob"}, headers=h)
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/admin/jobs", json={"kind": "okjob"}, headers=h).json()["code"] == "JOB_IN_PROGRESS"
    assert client.post("/api/v1/admin/jobs", json={"kind": "nope"}, headers=h).status_code == 400
    assert client.post("/api/v1/admin/jobs", json={"kind": "DROP TABLE"}, headers=h).status_code == 400
    jobs = client.get("/api/v1/meta/jobs").json()["items"]
    assert jobs[0]["kind"] == "okjob" and "requestedBy" not in jobs[0]          # 공개 목록엔 요청 IP 없음
    admin = client.get("/api/v1/admin/jobs", headers=h).json()["items"]
    assert admin[0]["requested_by"]
    assert client.post(f"/api/v1/admin/jobs/{jobs[0]['jobId']}/cancel", headers=h).json()["status"] == "CANCELLED"
    sched = client.get("/api/v1/meta/schedule").json()
    assert {i["kind"] for i in sched["items"]} >= {"kma", "air", "care", "holidays", "post"}


def test_security_headers_etag_and_health(client):
    r = client.get("/api/v1/metrics")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-trace-id"]
    tag = r.headers["etag"]
    again = client.get("/api/v1/metrics", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    h = client.get("/api/v1/health").json()
    assert h["schema"]["upToDate"] and h["queue"]["queued"] >= 0
    prom = client.get("/metrics").text
    assert "atlas_http_request_duration_seconds" in prom and "atlas_http_not_modified_total" in prom


def test_rate_limit_returns_429(client, monkeypatch):
    from atlas.api import security

    counts: dict[str, int] = {}

    async def fake_hit(bucket, ip, limit, now=None):
        counts[bucket] = counts.get(bucket, 0) + 1
        return counts[bucket] <= 2, max(2 - counts[bucket], 0), 42

    monkeypatch.setattr(security, "hit", fake_hit)
    for _ in range(2):
        assert client.get("/api/v1/metrics").status_code == 200
    r = client.get("/api/v1/metrics")
    assert r.status_code == 429 and r.headers["retry-after"] == "42" and r.json()["code"] == "RATE_LIMITED"


def test_api_role_least_privilege(engine):
    """atlas_api 는 raw(원본 응답) 조회·DDL·데이터 변경 불가, 작업 요청·What-if 저장만 가능."""
    def as_api(sql: str):
        with engine.connect() as c:
            t = c.begin()
            try:
                c.execute(text("SET LOCAL ROLE atlas_api"))
                return c.execute(text(sql)).all() if sql.lstrip().upper().startswith("SELECT") else c.execute(text(sql))
            finally:
                t.rollback()

    assert as_api("SELECT count(*) FROM mart.admin_area")
    as_api("INSERT INTO ops.job (kind) VALUES ('calc')")
    for bad in ("SELECT * FROM raw.api_response LIMIT 1", "DELETE FROM mart.access_metric",
                "UPDATE ops.job SET kind = 'x'", "CREATE TABLE mart.x (a int)", "DROP TABLE mart.metric_def",
                "SELECT * FROM stg.post_facility LIMIT 1"):
        with pytest.raises(DBAPIError, match="permission denied|must be owner"):
            as_api(bad)
    with engine.connect() as c:
        cfg = c.execute(text("SELECT rolconfig FROM pg_roles WHERE rolname = 'atlas_api'")).scalar()
    assert any(x.startswith("statement_timeout=") for x in cfg)


def test_error_log_collects_all_sources(client, fake_jobs):
    from atlas.api import errors as api_errors

    queue.enqueue("boom")
    worker.execute(queue.claim("w1"))                                              # 작업 실패
    api_errors.record("trace123", "GET", "/api/v1/x", RuntimeError("boom serviceKey=SECRET123"))   # API 예외
    r = client.get("/api/v1/meta/errors").json()
    by = {i["source"]: i for i in r["items"]}
    assert set(by) >= {"API", "작업"}
    assert "serviceKey=***" in by["API"]["message"] and "SECRET123" not in by["API"]["line"]      # 키 마스킹
    assert by["작업"]["line"].split(" [작업] ")[1].startswith("#") and "수집 실패" in by["작업"]["line"]
    assert r["items"][0]["at"] >= r["items"][-1]["at"]                                           # 최신순


def test_long_job_does_not_block_short_lane(fake_jobs, monkeypatch, engine):
    """차선 분리 — long 작업이 도는 동안 short 작업(예보 등)이 먼저 끝나야 함. 워커 생존 신호도 기록."""
    from atlas.core.config import get_settings

    monkeypatch.setattr(get_settings(), "atlas_schedule", "")
    release, long_started, short_done = threading.Event(), threading.Event(), threading.Event()

    def slow(_):
        long_started.set()
        release.wait(10)
        return {}

    def fast(_):
        short_done.set()
        return {}

    monkeypatch.setitem(registry.JOBS, "slowjob", JobSpec("slowjob", "느린 작업", slow, long=True))
    monkeypatch.setitem(registry.JOBS, "fastjob", JobSpec("fastjob", "빠른 작업", fast))
    assert registry.lane_of("slowjob") == "long" and registry.lane_of("fastjob") == "short"
    stop = threading.Event()
    t = threading.Thread(target=worker.run_forever, kwargs={"poll_s": 2.0, "stop": stop}, daemon=True)
    t.start()
    try:
        queue.enqueue("slowjob")
        assert long_started.wait(5)
        queue.enqueue("fastjob")                      # 나중에 들어왔지만
        assert short_done.wait(5), "long 작업에 막히지 않고 short 차선이 처리해야 함"
        lanes = {w["lane"]: w for w in queue.workers()}
        assert set(lanes) == {"short", "long"} and lanes["long"]["job_id"] is not None
    finally:
        release.set()
        stop.set()
        with engine.begin() as c:
            c.execute(text("SELECT pg_notify('atlas_jobs', 'stop')"))
        t.join(10)
    assert not t.is_alive()
    assert queue.workers() == []                       # 정상 종료 시 생존 신호 행 삭제


def test_health_live_and_workers(client):
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json()["workers"] == []


def test_worker_survives_db_disconnect(fake_jobs, monkeypatch, engine):
    """DB 가 연결을 모두 끊어도(장애 복구·재시작) 차선이 죽지 않고 다시 연결해 작업을 처리."""
    from atlas.core.config import get_settings

    monkeypatch.setattr(get_settings(), "atlas_schedule", "")
    monkeypatch.setattr(worker, "RETRY_MAX_S", 1)
    stop = threading.Event()
    t = threading.Thread(target=worker.run_forever, kwargs={"poll_s": 1.0, "stop": stop}, daemon=True)
    t.start()
    try:
        import time

        time.sleep(1.0)
        with engine.begin() as c:                           # 이 DB 의 다른 연결(워커 LISTEN·풀)을 모두 끊음
            n = c.execute(text("""SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
                                   WHERE datname = current_database() AND pid <> pg_backend_pid()""")).scalar()
        assert n >= 2
        time.sleep(0.5)
        queue.enqueue("okjob", {"recalc": False})
        deadline = time.time() + 10
        while time.time() < deadline and queue.recent(1)[0]["status"] != "DONE":
            time.sleep(0.2)
        assert queue.recent(1)[0]["status"] == "DONE"
        assert t.is_alive() and {w["lane"] for w in queue.workers()} == {"short", "long"}
    finally:
        stop.set()
        with engine.begin() as c:
            c.execute(text("SELECT pg_notify('atlas_jobs', 'stop')"))
        t.join(10)
    assert not t.is_alive()
