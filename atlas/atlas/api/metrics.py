"""Prometheus 지표 — GET /metrics (127.0.0.1:8100 에만 노출, web 프록시 경로 아님).

uvicorn 워커가 여럿이면 PROMETHEUS_MULTIPROC_DIR 로 프로세스별 값을 모아 냅니다(컨테이너 기동 때 디렉터리 비움).
경로 라벨은 실제 URL 이 아니라 라우트 템플릿(/api/v1/areas/{adm_cd})이라 카디널리티가 늘지 않습니다.
"""
from __future__ import annotations

import os
import time

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_S = Histogram("atlas_http_request_duration_seconds", "API 응답 시간", ["method", "route", "status"],
                      buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
RATE_LIMITED = Counter("atlas_rate_limited_total", "속도 제한으로 거절한 요청", ["bucket"])
CACHE = Counter("atlas_cache_requests_total", "Redis 캐시 조회", ["result"])
NOT_MODIFIED = Counter("atlas_http_not_modified_total", "ETag 일치로 본문 없이 돌려준 응답(304)")


def render() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
        return generate_latest(reg), CONTENT_TYPE_LATEST
    from prometheus_client import REGISTRY

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()
        status = {"code": 500}

        async def send_wrap(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        try:
            await self.app(scope, receive, send_wrap)
        finally:
            route = scope.get("route")
            REQUEST_S.labels(scope["method"], getattr(route, "path", "unmatched"),
                             str(status["code"])).observe(time.perf_counter() - t0)
