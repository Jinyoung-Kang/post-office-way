from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from atlas.api import cache
from atlas.core.db import get_engine
from atlas.core.migrate import pending

router = APIRouter(tags=["health"])


@router.get("/health", summary="DB·Redis·스키마·작업 큐 상태 (FR-701)")
def health():
    db_ok, postgis, counts, schema, queue = False, None, {}, None, None
    try:
        eng = get_engine()
        with eng.connect() as c:
            postgis = c.execute(text("SELECT postgis_lib_version()")).scalar()
            counts = dict(c.execute(text("""SELECT
                (SELECT count(*) FROM mart.post_facility_hist WHERE is_current) AS facilities,
                (SELECT count(*) FROM mart.admin_area) AS areas,
                (SELECT count(*) FROM mart.calc_run WHERE status = 'DONE') AS calc_runs""")).mappings().one())
            # 대기 작업이 오래 쌓여 있으면 워커가 꺼져 있는 것 (compose 서비스 worker 확인)
            queue = dict(c.execute(text("""SELECT count(*) FILTER (WHERE status = 'QUEUED') AS queued,
                                                  count(*) FILTER (WHERE status = 'RUNNING') AS running,
                                                  extract(epoch FROM now() - min(created_at) FILTER (WHERE status = 'QUEUED'))
                                                      AS oldest_queued_s
                                             FROM ops.job""")).mappings().one())
        todo = pending(eng)
        schema = {"upToDate": not todo, "pending": todo}
        db_ok = True
    except Exception as e:  # noqa: BLE001
        counts = {"error": type(e).__name__}
    redis_ok = cache.ping()
    ok = db_ok and bool(schema and schema["upToDate"])
    body = {"status": "ok" if ok else "degraded", "db": db_ok, "redis": redis_ok, "postgis": postgis,
            "schema": schema, "queue": _queue(queue),
            "counts": counts}
    return JSONResponse(body, status_code=200 if ok else 503)


def _queue(q: dict | None) -> dict | None:
    if q is None:
        return None
    age = q.get("oldest_queued_s")
    return {"queued": q["queued"], "running": q["running"], "oldestQueuedS": round(float(age), 1) if age is not None else None}
