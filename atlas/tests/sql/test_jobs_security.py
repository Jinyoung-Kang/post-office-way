"""작업 큐(ops.job)·워커·관리 API, 최소 권한 역할(atlas_api), 보안 헤더·ETag·속도 제한 — PostGIS 테스트 DB.

작업 실행 함수는 가짜로 바꿔 수집 API 를 부르지 않습니다.
"""
import os
import threading
import time

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
    assert "atlas_cache_requests_total" in prom    # 캐시 지표는 core/cache.py 에 있어도 /metrics 로 노출


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
    assert r.json()["traceId"] == r.headers["x-trace-id"]                 # 오류 형식 {code, message, traceId}


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
    as_api("INSERT INTO ops.error_ack (entry_id) VALUES ('api:1') ON CONFLICT (entry_id) DO NOTHING")   # 오류 로그 지우기
    for bad in ("SELECT * FROM raw.api_response LIMIT 1", "DELETE FROM mart.access_metric",
                "DELETE FROM ops.app_error", "DELETE FROM ops.error_ack",
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


def test_error_log_ack_hides_entry_but_keeps_source(client, fake_jobs, engine):
    """지우기 = 확인 표시 — 관리 토큰 필요, 로그에서만 빠지고 원본(작업 이력)은 남음, 같은 항목 두 번은 1건."""
    from atlas.api import errors as api_errors

    queue.enqueue("boom")
    worker.execute(queue.claim("w1"))
    api_errors.record("trace456", "GET", "/api/v1/y", RuntimeError("boom"))
    items = client.get("/api/v1/meta/errors").json()["items"]
    ids = {i["source"]: i["id"] for i in items}
    assert ids["작업"].startswith("job:") and ids["API"].startswith("api:")

    body = {"ids": [ids["작업"]]}
    assert client.post("/api/v1/admin/errors/ack", json=body).status_code == 401
    assert client.post("/api/v1/admin/errors/ack", json=body, headers={"X-Admin-Token": "x" * 32}).status_code == 401
    h = {"X-Admin-Token": "t" * 32}
    for bad in ({"ids": []}, {"ids": ["job:1; DROP"]}, {"ids": ["x:1"]}, {"ids": ["api:1"] * 501}, {}):
        r = client.post("/api/v1/admin/errors/ack", json=bad, headers=h)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", bad
    r = client.post("/api/v1/admin/errors/ack", json={"ids": [ids["작업"], ids["작업"]]}, headers=h).json()
    assert r == {"acked": 1, "requested": 2}
    assert client.post("/api/v1/admin/errors/ack", json=body, headers=h).json()["acked"] == 0      # 다시 지워도 그대로

    left = {i["source"] for i in client.get("/api/v1/meta/errors").json()["items"]}
    assert "작업" not in left and "API" in left
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM ops.job WHERE status = 'FAILED'")).scalar() == 1   # 원본 이력은 그대로
        assert c.execute(text("SELECT acked_by FROM ops.error_ack")).scalar()                        # 누가 지웠는지


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


def test_isolated_job_runs_in_child_process_and_propagates_errors(clean, monkeypatch, tmp_path):
    """무거운 작업(isolate)은 자식 프로세스에서 — 결과·예외가 그대로 돌아오고, 워커 메모리에 남지 않음."""
    monkeypatch.setenv("OSM_DIR", str(tmp_path))                 # 자식(spawn)은 환경 변수로 설정을 다시 읽음
    assert registry.get("walk").isolate and registry.get("osm").isolate
    out = worker.run_isolated("walk", {})
    assert "skipped" in out                                     # 그래프가 없으면 건너뜀
    with pytest.raises(RuntimeError, match="KeyError"):          # 자식의 예외는 '종류: 메시지' 로 전달 (R9)
        worker.run_isolated("no-such-job", {})


def test_csp_report_recorded_once_filtered_and_scrubbed(client, engine, monkeypatch):
    """CSP 위반 보고 → 오류 로그 '보안 정책'. 쿼리 문자열 제거, 같은 위반 1시간에 한 번, 카카오 eval·확장 프로그램은 무시."""
    from atlas.core import cache

    seen: set[str] = set()
    monkeypatch.setattr(cache, "set_nx", lambda k, v, ttl: not (k in seen or seen.add(k)))
    monkeypatch.setattr(cache, "incr", lambda k, ttl: len(seen))      # Redis 없이 돌려도 시간당 상한 안쪽
    url = "/api/v1/csp-report"
    old = {"csp-report": {"document-uri": "http://localhost:3100/banks?token=abc", "effective-directive": "script-src-elem",
                          "blocked-uri": "https://t1.kakaocdn.net/mapjsapi/js/main/4.5.28/kakao.js?v=secret"}}
    h = {"Content-Type": "application/csp-report"}
    assert client.post(url, json=old, headers=h).status_code == 204
    assert client.post(url, json=old, headers=h).status_code == 204          # 같은 위반 — 다시 기록하지 않음
    ignored = [{"csp-report": {"effective-directive": "script-src", "blocked-uri": "eval",
                               "source-file": "https://t1.kakaocdn.net/mapjsapi/js/main/4.5.28/kakao.js"}},
               {"csp-report": {"effective-directive": "script-src", "blocked-uri": "chrome-extension://abc/x.js"}}]
    for b in ignored:
        client.post(url, json=b, headers=h)
    new = [{"type": "csp-violation", "body": {"documentURL": "http://localhost:3100/", "effectiveDirective": "img-src",
                                              "blockedURL": "https://tiles.example.com/1/2/3.png"}}]
    assert client.post(url, json=new, headers={"Content-Type": "application/reports+json"}).status_code == 204
    assert client.post(url, content=b"x" * (17 * 1024), headers=h).status_code == 413
    assert client.post(url, content=b"not json", headers=h).status_code == 204
    assert client.post(url, json={"csp-report": {"blocked-uri": 1, "line-number": "x"}}, headers=h).status_code == 204  # 퍼징
    with engine.connect() as c:
        rows = c.execute(text("SELECT path, error_type, message FROM ops.app_error WHERE source = 'csp' ORDER BY error_id")).all()
    assert [r.error_type for r in rows] == ["script-src-elem", "img-src"]
    assert rows[0].path == "/banks" and "secret" not in rows[0].message and "token" not in rows[0].path
    errs = client.get("/api/v1/meta/errors").json()["items"]
    assert {e["source"] for e in errs if e["title"].startswith("CSP")} == {"보안 정책"}


def test_stored_run_and_job_errors_are_masked(clean, engine):
    """수집·작업 실패 원문(SQL·바인드 값·키)을 저장 전에 가리고, 공개 목록에도 요약만 (S6)."""
    from fastapi.testclient import TestClient

    from atlas.api.main import app
    from atlas.ops import runs as crun

    raw = ("OperationalError: boom serviceKey=SECRETVALUE123 [SQL: SELECT * FROM x WHERE a = %(a)s] "
           "[parameters: {'a': 'private-input'}] (Background on this error at: https://sqlalche.me/e/20/e3q8)")
    rid = crun.start_run("POST_AREA", check_running=False)
    crun.finish_run(rid, "FAILED", {}, error=raw)
    jid = queue.enqueue("okjob")
    queue.claim("w1")
    queue.finish(jid, False, {}, error=raw, worker="w1")
    with engine.connect() as c:
        stored = [c.execute(text("SELECT error FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).scalar(),
                  c.execute(text("SELECT error FROM ops.job WHERE job_id = :j"), {"j": jid}).scalar()]
    for s in stored:
        assert "SECRETVALUE123" not in s and "[SQL" not in s and "private-input" not in s and "boom" in s
    with TestClient(app) as cl:
        listed = cl.get("/api/v1/meta/collect-runs").json()["items"][0]["error"]
    assert "[SQL" not in listed and "SECRETVALUE123" not in listed


def _csp(origin: str) -> dict:
    return {"csp-report": {"document-uri": "http://localhost:3100/", "effective-directive": "img-src",
                           "blocked-uri": f"https://{origin}/x.png"}}


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="시간당 카운터는 Redis 가 필요 (make test 는 켬)")
def test_csp_report_flood_is_capped_per_hour(client, engine, monkeypatch):
    """출처를 바꿔 가며 보내도(중복 억제가 안 통함) 시간당 상한까지만 오류 로그에 남김 (S7)."""
    from atlas.features import csp_reports

    monkeypatch.setattr(csp_reports, "HOURLY_MAX", 5)
    for i in range(20):
        client.post("/api/v1/csp-report", json=_csp(f"spam{i}.example"), headers={"Content-Type": "application/csp-report"})
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM ops.app_error WHERE source = 'csp'")).scalar()
    assert n == 5


def test_csp_report_not_recorded_without_redis(client, engine, monkeypatch):
    """Redis 가 없으면 중복 억제·상한을 지킬 수 없으므로 기록하지 않음(로그에만) — 공개 쓰기 경로라 닫힌 쪽으로."""
    import redis as redis_mod

    from atlas.core import cache

    class Down:
        def __getattr__(self, name):
            def f(*a, **k):
                raise redis_mod.ConnectionError("down")
            return f

    monkeypatch.setattr(cache, "client", lambda: Down())
    client.post("/api/v1/csp-report", json=_csp("cdn.example"), headers={"Content-Type": "application/csp-report"})
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM ops.app_error WHERE source = 'csp'")).scalar() == 0


def test_reap_closes_orphan_runs_so_retry_works(fake_jobs, engine):
    """워커가 죽어 작업을 정리(reap)하면 그 작업이 연 실행 기록도 닫혀야 재시도가 '이미 실행 중'으로 실패하지 않음 (R1)."""
    from atlas.ops import runs
    from atlas.core.jobctx import current_job_id

    jid = queue.enqueue("okjob")
    job = queue.claim("w1")
    tok = current_job_id.set(job["job_id"])
    try:
        rid = runs.start_run("POST_AREA")              # 수집 도중 워커가 죽음 → RUNNING 으로 남음
    finally:
        current_job_id.reset(tok)
    with engine.begin() as c:
        c.execute(text("UPDATE ops.job SET heartbeat_at = now() - interval '1 hour' WHERE job_id = :j"), {"j": jid})
    queue.reap()
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).scalar() == "FAILED"
    runs.start_run("POST_AREA")                          # 재시도가 막히지 않음


def test_chain_while_same_kind_running_queues_a_new_one(fake_jobs, engine):
    """수집이 끝났을 때 계산이 '실행 중'이면 그 계산은 이미 스냅샷을 찍어 새 자료가 빠짐 → 새 계산이 대기열에 들어가야 하고,
    같은 종류가 실행 중인 동안에는 가져가지 않음 (R2)."""
    queue.enqueue("calc")
    running = queue.claim("w-short", kinds=["calc"])            # 계산 실행 중
    queue.enqueue("okjob")
    job = queue.claim("w-long", kinds=["okjob"])
    assert worker.execute(job)
    chained = queue.recent(10)
    new_calc = [r for r in chained if r["kind"] == "calc" and r["status"] == "QUEUED"]
    assert len(new_calc) == 1 and new_calc[0]["job_id"] != running["job_id"]
    assert queue.claim("w-short", kinds=["calc"]) is None       # 같은 종류가 실행 중이면 기다림
    queue.finish(running["job_id"], True, {})
    assert queue.claim("w-short", kinds=["calc"])["job_id"] == new_calc[0]["job_id"]
    with pytest.raises(queue.JobConflict):                      # 대기 중은 여전히 하나만
        queue.enqueue("calc")
        queue.enqueue("calc")


def test_job_with_only_failed_collect_runs_fails_and_skips_recalc(fake_jobs, engine, monkeypatch):
    """수집기가 실행 기록을 FAILED 로 남기고 정상 반환해도 작업은 FAILED, 재계산은 넣지 않음 (R6)."""
    from atlas.ops import runs

    rid = runs.start_run("NMC_CARE", check_running=False)
    runs.finish_run(rid, "FAILED", {}, error="받은 자료 없음")
    monkeypatch.setitem(registry.JOBS, "okjob", JobSpec("okjob", "테스트", lambda p: {"collectRunIds": [str(rid)]}, recalc=True))
    queue.enqueue("okjob")
    assert not worker.execute(queue.claim("w1"))
    job = queue.recent(1)[0]
    assert job["status"] == "FAILED" and "수집 실패" in job["error"]
    assert not [r for r in queue.recent(10) if r["kind"] == "calc"]       # 재계산 없음


def test_schedule_runs_while_short_lane_is_busy(fake_jobs, monkeypatch, engine):
    """short 차선이 오래 걸리는 작업을 도는 동안에도 스케줄 슬롯이 들어가야 함 — 예전에는 스케줄 확인이 short 차선 루프
    안이라 30분 창을 넘기면 슬롯이 조용히 건너뛰어졌음 (R7)."""
    from atlas.core.config import get_settings
    from atlas.jobs import scheduler

    monkeypatch.setattr(get_settings(), "atlas_schedule", "weather")
    release, busy = threading.Event(), threading.Event()

    def slow(_):
        busy.set()
        release.wait(15)
        return {}

    monkeypatch.setitem(registry.JOBS, "slowshort", JobSpec("slowshort", "느린 short 작업", slow))
    monkeypatch.setattr(scheduler, "due", lambda now, entries: [("kma", "kma@test-slot")] if entries and busy.is_set() else [])
    monkeypatch.setitem(registry.JOBS, "kma", JobSpec("kma", "예보(가짜)", lambda p: {}))
    monkeypatch.setattr(worker, "SCHEDULE_TICK_S", 0.5)
    stop = threading.Event()
    t = threading.Thread(target=worker.run_forever, kwargs={"poll_s": 1.0, "stop": stop}, daemon=True)
    t.start()
    try:
        queue.enqueue("slowshort")
        assert busy.wait(5)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not [j for j in queue.recent(10) if j["slot"] == "kma@test-slot"]:
            time.sleep(0.2)
        assert [j for j in queue.recent(10) if j["slot"] == "kma@test-slot"], "short 차선이 바빠도 슬롯이 들어가야 함"
    finally:
        release.set()
        stop.set()
        with engine.begin() as c:
            c.execute(text("SELECT pg_notify('atlas_jobs', 'stop')"))
        t.join(10)


def test_late_finish_from_reaped_worker_is_ignored(fake_jobs, engine):
    """정리(reap)된 뒤 다른 워커가 다시 가져간 작업을, 처음 워커가 늦게 끝내도 덮어쓰지 않음 (R8)."""
    jid = queue.enqueue("okjob")
    queue.claim("w1")
    with engine.begin() as c:
        c.execute(text("UPDATE ops.job SET heartbeat_at = now() - interval '1 hour' WHERE job_id = :j"), {"j": jid})
    queue.reap()
    assert queue.claim("w2")["job_id"] == jid
    queue.heartbeat(jid, worker="w1")
    queue.finish(jid, True, {"from": "w1"}, worker="w1")          # 늦게 끝난 처음 워커
    with engine.connect() as c:
        st, w, res = c.execute(text("SELECT status, worker, result FROM ops.job WHERE job_id = :j"), {"j": jid}).one()
    assert (st, w) == ("RUNNING", "w2") and res is None
    queue.finish(jid, True, {"from": "w2"}, worker="w2")
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM ops.job WHERE job_id = :j"), {"j": jid}).scalar() == "DONE"


def test_error_log_time_is_kst_regardless_of_process_timezone(client, engine, monkeypatch):
    """오류 로그 한 줄의 시각은 서비스 기준(KST) — 프로세스 시간대(TZ)에 기대지 않음."""
    with engine.begin() as c:
        c.execute(text("""INSERT INTO ops.app_error (source, method, path, error_type, message, at)
                          VALUES ('api', 'GET', '/x', 'E', 'm', '2026-10-08 00:00:00+00')"""))
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        line = client.get("/api/v1/meta/errors").json()["items"][0]["line"]
    finally:
        monkeypatch.undo()
        time.tzset()
    assert line.startswith("2026-10-08 09:00:00")
