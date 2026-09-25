"""API 보안 계층 — 신뢰 프록시 뒤 클라이언트 IP, Redis 고정 창 속도 제한, 보안 헤더 (ADR-013).

- 브라우저 → web(Next, 같은 출처 rewrite) → api 경로라 api 가 보는 주소는 web 컨테이너입니다. 사설망(신뢰 프록시)에서
  온 요청만 X-Forwarded-For 첫 값을 믿고, 그 밖에서는 헤더를 무시해 IP 위조로 제한을 피하지 못하게 합니다.
- 속도 제한은 Redis INCR+EXPIRE(고정 1분 창). Redis 가 없으면 제한 없이 통과(fail-open) — 캐시와 같은 선택 요소.
- 모든 미들웨어는 순수 ASGI 로 작성(BaseHTTPMiddleware 의 응답 스트림 복사 비용 없음).
"""
from __future__ import annotations

import ipaddress
import logging
import time
from functools import lru_cache
from typing import Any

import redis.asyncio as aioredis
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atlas.core.config import get_settings

log = logging.getLogger("atlas.security")

# (메서드, 경로 접두사) → (버킷, 1분당 허용 수). 위에서부터 첫 일치
RULES: tuple[tuple[str, str, str, int], ...] = (
    ("POST", "/api/v1/admin", "admin", 10),       # 토큰 대입 방지
    ("GET", "/api/v1/admin", "admin", 30),
    ("POST", "/api/v1/whatif", "heavy", 30),      # 부분 재계산·KNN
    ("POST", "/api/v1/plan", "heavy", 30),        # 탐욕 배치 (수 초)
    ("*", "/api/v1", "default", 600),
)


@lru_cache
def _trusted() -> list[ipaddress._BaseNetwork]:
    return [ipaddress.ip_network(x.strip()) for x in get_settings().trusted_proxies.split(",") if x.strip()]


def _is_trusted(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(ip in net for net in _trusted())


def ip_from_scope(scope: Scope) -> str:
    peer = (scope.get("client") or ("", 0))[0]
    if _is_trusted(peer):
        for k, v in scope.get("headers") or []:
            if k == b"x-forwarded-for":
                first = v.decode("latin-1").split(",")[0].strip()
                try:
                    return str(ipaddress.ip_address(first))
                except ValueError:
                    break
    return peer or "unknown"


def client_ip(request: Request) -> str:
    return ip_from_scope(request.scope)


def rule_for(method: str, path: str) -> tuple[str, int] | None:
    for m, prefix, bucket, limit in RULES:
        if (m == "*" or m == method) and path.startswith(prefix):
            return bucket, limit
    return None


@lru_cache
def _redis() -> aioredis.Redis:
    return aioredis.Redis.from_url(get_settings().redis_url, socket_timeout=0.3, socket_connect_timeout=0.3)


async def hit(bucket: str, ip: str, limit: int, now: float | None = None) -> tuple[bool, int, int]:
    """(허용 여부, 남은 수, 창이 끝날 때까지 초). Redis 오류면 허용."""
    now = now or time.time()
    window = int(now // 60)
    key = f"rl:{bucket}:{ip}:{window}"
    try:
        async with _redis().pipeline(transaction=True) as p:
            p.incr(key)
            p.expire(key, 70)
            count, _ = await p.execute()
    except Exception:  # Redis 는 선택 요소 — 제한 없이 통과
        return True, limit, 0
    reset = 60 - int(now % 60)
    return count <= limit, max(limit - count, 0), reset


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not get_settings().rate_limit_enabled:
            return await self.app(scope, receive, send)
        rule = rule_for(scope["method"], scope["path"])
        if not rule:
            return await self.app(scope, receive, send)
        bucket, limit = rule
        ip = ip_from_scope(scope)
        ok, remaining, reset = await hit(bucket, ip, limit)
        headers = [(b"x-ratelimit-limit", str(limit).encode()), (b"x-ratelimit-remaining", str(remaining).encode()),
                   (b"x-ratelimit-reset", str(reset).encode())]
        if not ok:
            from atlas.api import metrics

            metrics.RATE_LIMITED.labels(bucket).inc()
            log.warning("rate limited", extra={"bucket": bucket, "ip": ip, "path": scope["path"]})
            body = ('{"code":"RATE_LIMITED","message":"요청이 너무 많습니다. %d초 뒤 다시 시도하세요."}' % reset).encode()
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", str(reset).encode()),
                                    *headers]})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                msg["headers"] = [*msg.get("headers", []), *headers]
            await send(msg)

        await self.app(scope, receive, send_with)


# API 응답(JSON)용 — 문서(/docs)는 Swagger UI 가 CDN 스크립트를 쓰므로 CSP 를 따로 둠
_BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
]
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_DOCS_CSP = (b"content-security-policy",
             b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
             b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
             b"frame-ancestors 'none'")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        extra: list[tuple[bytes, bytes]] = [_DOCS_CSP if path in ("/docs", "/redoc") else _API_CSP]
        if method != "GET" or path.startswith("/api/v1/admin"):
            extra.append((b"cache-control", b"no-store"))

        async def send_with(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                have = {k.lower() for k, _ in msg.get("headers", [])}
                msg["headers"] = [*msg.get("headers", []), *[(k, v) for k, v in (*_BASE_HEADERS, *extra) if k not in have]]
            await send(msg)

        await self.app(scope, receive, send_with)


def describe() -> dict[str, Any]:
    return {"rules": [{"method": m, "prefix": p, "bucket": b, "perMinute": n} for m, p, b, n in RULES]}
