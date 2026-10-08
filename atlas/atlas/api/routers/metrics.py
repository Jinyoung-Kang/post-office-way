from __future__ import annotations

from fastapi import APIRouter

from atlas.core.db import get_engine
from atlas.features import meta

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", summary="지표 정의 목록 (FR-504)")
def list_metrics():
    with get_engine().connect() as c:
        return meta.metric_catalog(c)
