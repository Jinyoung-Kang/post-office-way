"""전국 개요 — 개요 화면의 큰 숫자·분포·취약 지역 (최신 calc_run 기준)."""
from __future__ import annotations

from fastapi import APIRouter

from atlas.core.db import get_engine
from atlas.features.overview import service as svc

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("", summary="전국 개요 — 시설·거리 분포·고령인구·취약 지역 (최신 calc_run)")
def overview(calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.overview(c, calcRunId)
