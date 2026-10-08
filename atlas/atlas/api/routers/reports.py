"""브라우저 보고 수신 — CSP 위반(report-uri · Reporting API) → ops.app_error (출처 '보안 정책').

공개 엔드포인트라 본문 16KB 제한, 속도 제한(분당 30), 같은 (지시어, 막힌 출처)는 1시간에 한 번만 기록.
주소의 쿼리 문자열은 저장하지 않음(토큰·개인정보가 섞일 수 있음). 응답은 늘 204.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from atlas.core import cache
from atlas.core.db import get_engine

log = logging.getLogger(__name__)
router = APIRouter(tags=["reports"])
MAX_BODY = 16 * 1024
HOURLY_MAX = 100                  # 오류 로그에 남기는 CSP 보고 상한(전체, 시간당) — 정상이면 하루 몇 건
NOISE = ("chrome-extension", "moz-extension", "safari-extension", "safari-web-extension", "about")


def _clean(u: str | None) -> str:
    """URL → 쿼리·조각을 뗀 출처+경로. 'eval'·'inline' 같은 키워드는 그대로."""
    if not u:
        return ""
    if "://" not in u:
        return u[:40]
    p = urlsplit(u)
    return f"{p.scheme}://{p.netloc}{p.path}"[:300]


def _s(v: Any) -> str | None:
    """보고 값은 아무나 보낼 수 있어 형식을 믿지 않음 — 문자열로만 다룸 (퍼징에서 숫자 값이 500 을 냈음)."""
    return None if v is None else str(v)[:2000]


def _normalize(body: Any) -> list[dict[str, Any]]:
    """report-uri 형식 {"csp-report": {...}} 과 Reporting API 형식 [{"type": "csp-violation", "body": {...}}] 둘 다."""
    out = []
    if isinstance(body, dict) and isinstance(body.get("csp-report"), dict):
        r = body["csp-report"]
        out.append({"directive": _s(r.get("effective-directive") or r.get("violated-directive")), "blocked": _s(r.get("blocked-uri")),
                     "document": _s(r.get("document-uri")), "source": _s(r.get("source-file")), "line": _s(r.get("line-number"))})
    elif isinstance(body, list):
        for item in body[:20]:
            if isinstance(item, dict) and item.get("type") == "csp-violation" and isinstance(item.get("body"), dict):
                r = item["body"]
                out.append({"directive": _s(r.get("effectiveDirective")), "blocked": _s(r.get("blockedURL")),
                            "document": _s(r.get("documentURL")), "source": _s(r.get("sourceFile")), "line": _s(r.get("lineNumber"))})
    return out


def _ignored(r: dict[str, Any]) -> bool:
    blocked, source = str(r.get("blocked") or ""), str(r.get("source") or "")
    if not r.get("directive"):                         # 지시어 없는 보고는 형식이 맞지 않음 — 버림
        return True
    if blocked == "eval" and "kakao" in source:      # 카카오 SDK 의 eval 시도는 일부러 막아 둠(ADR-013)
        return True
    return blocked.startswith(NOISE) or source.startswith(NOISE)


@router.post("/csp-report", status_code=204, summary="CSP 위반 보고 수신 (브라우저가 보냄)", include_in_schema=False)
async def csp_report(request: Request) -> Response:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return Response(status_code=413)
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY:
            return Response(status_code=413)
    try:
        reports = _normalize(json.loads(raw or b"null"))
    except (ValueError, UnicodeDecodeError):
        return Response(status_code=204)
    await run_in_threadpool(_record, reports)          # DB·Redis 는 동기 — 이벤트 루프를 막지 않게
    return Response(status_code=204)


def _record(reports: list[dict[str, Any]]) -> None:
    for r in reports:
        if _ignored(r):
            continue
        directive = str(r.get("directive") or "unknown")[:40]
        blocked = _clean(r.get("blocked"))
        blocked_origin = blocked.split("/", 3)[2] if "://" in blocked else blocked
        if not cache.set_nx(f"csp:{directive}:{blocked_origin}", "1", ttl=3600):
            continue                                   # 같은 위반은 1시간에 한 번만 (Redis 가 없으면 기록하지 않음)
        n = cache.incr(f"csp:hour:{int(time.time() // 3600)}", ttl=3600)
        if n is None or n > HOURLY_MAX:                # 출처를 바꿔 가며 보내도 시간당 상한까지만 (S7)
            log.warning("csp report dropped (hourly cap)", extra={"directive": directive, "blocked": blocked_origin})
            continue
        page = urlsplit(r.get("document") or "").path[:200] or "-"
        src = _clean(r.get("source"))
        msg = f"{directive} 가 {blocked or '?'} 를 막음" + (f" (스크립트 {src}:{r.get('line')})" if src else "")
        try:
            with get_engine().begin() as c:
                c.execute(text("""INSERT INTO ops.app_error (source, method, path, error_type, message)
                                  VALUES ('csp', 'CSP', :p, :e, :m)"""), {"p": page, "e": directive, "m": msg[:1000]})
        except Exception:  # 보고 저장 실패가 응답을 막지 않게
            log.warning("csp report record failed")
        log.warning("csp violation", extra={"directive": directive, "blocked": blocked_origin, "page": page})
