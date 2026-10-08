from __future__ import annotations

from fastapi import APIRouter

from atlas.core.db import get_engine
from atlas.features import quality as svc

router = APIRouter(prefix="/dq", tags=["dq"])


@router.get("/summary", summary="품질 요약 — 최근 수집 run(종류별)·계산 run 의 규칙별 건수 (FR-602)")
def summary(collectRunId: str | None = None, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.summary(c, collectRunId, calcRunId)


@router.get("/issues", summary="품질 이슈 상세 목록 (필터·페이지)")
def issues(collectRunId: str | None = None, calcRunId: str | None = None, checkCode: str | None = None,
           severity: str | None = None, scope: str = "latest", page: int = 1, size: int = 50):
    """scope=latest(기본): run 을 지정하지 않으면 최신 run 들의 이슈만 · scope=all: 과거 run 포함."""
    with get_engine().connect() as c:
        return svc.issues(c, collectRunId, calcRunId, checkCode, severity, scope, page, size)
