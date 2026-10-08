"""브라우저 보고 수신 — CSP 위반(report-uri · Reporting API) → ops.app_error (출처 '보안 정책').

공개 엔드포인트라 본문 16KB 제한, 속도 제한(분당 30), 같은 (지시어, 막힌 출처)는 1시간에 한 번만 기록.
주소의 쿼리 문자열은 저장하지 않음(토큰·개인정보가 섞일 수 있음). 응답은 늘 204.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from atlas.features import csp_reports

router = APIRouter(tags=["reports"])
MAX_BODY = 16 * 1024


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
        reports = csp_reports.normalize(json.loads(raw or b"null"))
    except (ValueError, UnicodeDecodeError):
        return Response(status_code=204)
    await run_in_threadpool(csp_reports.record, reports)          # DB·Redis 는 동기 — 이벤트 루프를 막지 않게
    return Response(status_code=204)
