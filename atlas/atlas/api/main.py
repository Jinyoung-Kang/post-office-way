"""FastAPI 앱 — Base URL /api/v1, OpenAPI 문서 /docs."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from atlas.api import errors
from atlas.api.routers import admin, areas, banks, dq, facilities, health, meta, metrics, overview, plan, visit, whatif
from atlas.core.db import get_engine
from atlas.core.logging import setup_logging
from atlas.core.migrate import migrate

log = logging.getLogger("atlas.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    applied = migrate(get_engine())
    log.info("api started", extra={"migrationsApplied": applied})
    yield


app = FastAPI(title="Postal Access Atlas API", version="0.1.0", lifespan=lifespan,
              docs_url="/docs", openapi_url="/openapi.json",
              description="우체국 접근성 아틀라스 — 분석용 지표이며 공식 통계가 아닙니다.")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3100", "http://127.0.0.1:3100"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])
errors.install(app)


@app.middleware("http")
async def trace(request: Request, call_next):
    request.state.trace_id = uuid.uuid4().hex[:16]
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    response.headers["X-Trace-Id"] = request.state.trace_id
    response.headers["Server-Timing"] = f"app;dur={ms}"
    if request.url.path != "/api/v1/health":
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code, "ms": ms, "traceId": request.state.trace_id})
    return response


for r in (health, meta, overview, facilities, banks, areas, metrics, whatif, plan, visit, dq, admin):
    app.include_router(r.router, prefix="/api/v1")
