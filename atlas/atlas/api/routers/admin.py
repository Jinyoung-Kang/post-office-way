"""관리 API — 수집·계산 작업을 큐에 넣습니다(X-Admin-Token 필수). 실행은 워커 몫이라 API 프로세스는 가볍게 유지.

이전에는 API 프로세스 스레드에서 수집기를 돌렸지만, 그러면 API 가 쓰기 권한·긴 작업·재시작 시 유실을 떠안습니다.
이제는 ops.job 에 INSERT + NOTIFY 만 하고 202 를 돌려줍니다 (ADR-012).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from atlas.api.common import jsonable
from atlas.api.errors import ApiError
from atlas.api.security import client_ip
from atlas.core.config import get_settings
from atlas.jobs import queue, registry

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("atlas.audit")


def _auth(token: str | None) -> None:
    expected = get_settings().admin_token
    if not expected:
        raise ApiError(503, "ADMIN_DISABLED", ".env 에 ADMIN_TOKEN 이 없어 관리 API 가 꺼져 있습니다.")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise ApiError(401, "UNAUTHORIZED", "X-Admin-Token 이 일치하지 않습니다.")


class JobRequest(BaseModel):
    kind: str = Field(pattern=r"^[a-z0-9-]{2,20}$")
    params: dict = Field(default_factory=dict)


def _enqueue(request: Request, kind: str, params: dict) -> JSONResponse:
    try:
        spec = registry.get(kind)
    except KeyError as e:
        raise ApiError(400, "VALIDATION_ERROR", f"kind 는 {sorted(registry.JOBS)} 중 하나입니다.") from e
    if miss := spec.missing():
        raise ApiError(400, "KEY_MISSING", f".env 에 {', '.join(miss)} 가 없습니다.")
    ip = client_ip(request)
    try:
        jid = queue.enqueue(kind, params, source="api", requested_by=ip)
    except queue.JobConflict as e:
        raise ApiError(409, "JOB_IN_PROGRESS", str(e)) from e
    log.info("admin enqueue", extra={"jobId": jid, "kind": kind, "ip": ip})
    return JSONResponse({"jobId": jid, "kind": kind, "status": "QUEUED", "check": "/api/v1/meta/jobs"},
                        status_code=202)


@router.post("/jobs", status_code=202, summary="작업 요청 — 워커가 실행 (kind: post·sgis·kosis·oa·banks·road·geocheck·kma·air·care·holidays·calc)")
def post_job(req: JobRequest, request: Request, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return _enqueue(request, req.kind, req.params)


@router.post("/collect/{kind}", status_code=202, summary="수집 요청 (이전 경로 호환) → 작업 큐")
def trigger_collect(kind: str, request: Request, scope: str | None = None, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return _enqueue(request, kind, {"scope": scope} if scope and scope != "all" else {})


@router.post("/calc", status_code=202, summary="계산 요청 (이전 경로 호환) → 작업 큐")
def trigger_calc(request: Request, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return _enqueue(request, "calc", {})


@router.post("/jobs/{job_id}/cancel", summary="대기 중인 작업 취소")
def cancel_job(job_id: int, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    if not queue.cancel(job_id):
        raise ApiError(409, "JOB_NOT_QUEUED", f"jobId {job_id} 는 대기 중이 아닙니다.")
    return {"jobId": job_id, "status": "CANCELLED"}


@router.get("/jobs", summary="최근 작업 (요청 IP 포함 — 관리자용)")
def admin_jobs(limit: int = 50, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return {"items": jsonable(queue.recent(min(max(limit, 1), 200), with_requester=True))}
