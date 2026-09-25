"""FastAPI 앱 — Base URL /api/v1, OpenAPI 문서 /docs, Prometheus /metrics.

미들웨어(바깥 → 안): 추적 로그 → 지표 → 보안 헤더 → 속도 제한 → CORS → gzip → ETag → 라우터.
ETag 는 gzip 안쪽이라 압축 전 본문으로 해시하고, 304 는 압축할 본문이 없습니다.
API 는 DDL 권한이 없는 역할(atlas_api)로 접속하므로 기동 때 마이그레이션을 적용하지 않고 확인만 합니다.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atlas.api import errors, metrics
from atlas.api.etag import ETagMiddleware
from atlas.api.routers import (admin, areas, banks, calendar, dq, facilities, health, hubs, meta, metrics as metric_defs,
                               overview, plan, visit, whatif)
from atlas.api.security import RateLimitMiddleware, SecurityHeadersMiddleware, ip_from_scope
from atlas.core.config import get_settings
from atlas.core.db import get_engine
from atlas.core.logging import setup_logging
from atlas.core.migrate import migrate, pending

log = logging.getLogger("atlas.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if get_settings().migrate_on_start:          # 호스트 개발(make api-dev)용 — 소유자 역할로 접속할 때만
        log.info("api started", extra={"migrationsApplied": migrate(get_engine())})
    else:
        try:
            if todo := pending(get_engine()):
                log.error("schema behind — run `make migrate`", extra={"pending": todo})
        except Exception as e:  # DB 가 아직 준비 전이어도 기동은 하고 /health 가 503 을 알림
            log.error("schema check failed", extra={"error": str(e)[:200]})
        log.info("api started")
    yield


class TraceMiddleware:
    """요청마다 traceId 를 붙이고(오류 본문·응답 헤더·로그에 같은 값) 처리 시간을 남깁니다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tid = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["trace_id"] = tid
        t0 = time.perf_counter()
        status = {"code": 500}

        async def send_wrap(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
                ms = round((time.perf_counter() - t0) * 1000, 1)
                msg["headers"] = [*msg.get("headers", []), (b"x-trace-id", tid.encode()),
                                  (b"server-timing", f"app;dur={ms}".encode())]
            await send(msg)

        await self.app(scope, receive, send_wrap)
        if scope["path"] not in ("/api/v1/health", "/metrics"):
            log.info("request", extra={"method": scope["method"], "path": scope["path"], "status": status["code"],
                                       "ms": round((time.perf_counter() - t0) * 1000, 1), "traceId": tid,
                                       "ip": ip_from_scope(scope)})


app = FastAPI(title="우체국 가는 길 API (Postal Access Atlas)", version="0.2.0", lifespan=lifespan,
              docs_url="/docs", openapi_url="/openapi.json",
              description="우체국 가는 길 — 분석용 지표이며 공식 통계가 아닙니다.")
# add_middleware 는 나중에 넣은 것이 바깥 — 안쪽부터 넣음
app.add_middleware(ETagMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=5)   # 기본 9 는 수백 KB JSON 에서 CPU 병목
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3100", "http://127.0.0.1:3100"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Admin-Token", "If-None-Match"])
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(metrics.MetricsMiddleware)
app.add_middleware(TraceMiddleware)
errors.install(app)


@app.get("/metrics", include_in_schema=False)
def prometheus() -> Response:
    body, ctype = metrics.render()
    return Response(body, media_type=ctype)


for r in (health, meta, overview, facilities, banks, hubs, calendar, areas, metric_defs, whatif, plan, visit, dq, admin):
    app.include_router(r.router, prefix="/api/v1")
