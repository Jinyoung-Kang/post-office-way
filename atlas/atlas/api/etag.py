"""조건부 GET — 응답 본문 해시로 약한 ETag 를 붙이고, If-None-Match 가 같으면 304(본문 없음)로 돌려줍니다.

지도 GeoJSON(수 MB)·개요처럼 계산 실행이 바뀌기 전까지 같은 응답이 반복되는 경로에서 전송량을 없앱니다.
Cache-Control: no-cache 라 브라우저는 매번 재검증하므로 새 계산이 나오면 곧바로 새 본문을 받습니다.
"""
from __future__ import annotations

import hashlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY = 32 * 1024 * 1024


def _etag(body: bytes) -> bytes:
    return b'W/"' + hashlib.blake2b(body, digest_size=12).hexdigest().encode() + b'"'


def _matches(header: bytes, tag: bytes) -> bool:
    return any(t.strip() in (tag, b"*") for t in header.split(b","))


class ETagMiddleware:
    def __init__(self, app: ASGIApp, prefix: str = "/api/v1") -> None:
        self.app, self.prefix = app, prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or not scope["path"].startswith(self.prefix) \
                or scope["path"].startswith(self.prefix + "/admin"):
            return await self.app(scope, receive, send)
        inm = next((v for k, v in scope.get("headers") or [] if k == b"if-none-match"), None)
        start: Message | None = None
        chunks: list[bytes] = []
        passthrough = False

        async def send_buf(msg: Message) -> None:
            nonlocal start, passthrough
            if passthrough:
                return await send(msg)
            if msg["type"] == "http.response.start":
                start = msg
                # 200 이 아니거나 라우터가 이미 ETag 를 붙였으면(GeoJSON — 캐시에 해시까지 저장) 그대로 보냄
                if msg["status"] != 200 or any(k == b"etag" for k, _ in msg.get("headers", [])):
                    passthrough = True
                    await send(msg)
                return
            chunks.append(msg.get("body", b""))
            if sum(map(len, chunks)) > MAX_BODY:                  # 너무 크면 해시 없이 그대로
                passthrough = True
                await send(start)
                await send({"type": "http.response.body", "body": b"".join(chunks), "more_body": msg.get("more_body", False)})
                return
            if msg.get("more_body"):
                return
            body = b"".join(chunks)
            tag = _etag(body)
            headers = [(k, v) for k, v in start.get("headers", []) if k not in (b"etag", b"cache-control")]
            headers += [(b"etag", tag), (b"cache-control", b"no-cache")]
            if inm and _matches(inm, tag):
                from atlas.api import metrics

                metrics.NOT_MODIFIED.inc()
                keep = [(k, v) for k, v in headers if k not in (b"content-length", b"content-type")]
                await send({"type": "http.response.start", "status": 304, "headers": keep})
                await send({"type": "http.response.body", "body": b""})
                return
            headers = [(k, v) for k, v in headers if k != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, send_buf)
