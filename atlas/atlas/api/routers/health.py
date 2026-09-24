from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from atlas.api import cache
from atlas.core.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health", summary="DB·Redis 연결 상태 (FR-701)")
def health():
    db_ok, postgis, counts = False, None, {}
    try:
        with get_engine().connect() as c:
            postgis = c.execute(text("SELECT postgis_lib_version()")).scalar()
            counts = dict(c.execute(text("""SELECT
                (SELECT count(*) FROM mart.post_facility_hist WHERE is_current) AS facilities,
                (SELECT count(*) FROM mart.admin_area) AS areas,
                (SELECT count(*) FROM mart.calc_run WHERE status = 'DONE') AS calc_runs""")).mappings().one())
            db_ok = True
    except Exception as e:  # noqa: BLE001
        counts = {"error": type(e).__name__}
    redis_ok = cache.ping()
    body = {"status": "ok" if db_ok else "degraded", "db": db_ok, "redis": redis_ok, "postgis": postgis,
            "counts": counts}
    return JSONResponse(body, status_code=200 if db_ok else 503)
