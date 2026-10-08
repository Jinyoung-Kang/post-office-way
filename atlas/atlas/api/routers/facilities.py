from __future__ import annotations

from fastapi import APIRouter, Query

from atlas.core.db import get_engine
from atlas.features import facilities as svc

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get("", summary="시설 목록 (bbox, types, finOnly, q, page) (FR-501)")
def list_facilities(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
                    types: str | None = Query(None, description="post_div 목록, 예: 0,1,3"),
                    finOnly: bool = False, q: str | None = None, page: int = 1, size: int = 50):
    with get_engine().connect() as c:
        return svc.list_facilities(c, bbox, types, finOnly, q, page, size)


@router.get("/{hist_id}", summary="시설 상세 + 소속 행정구역 (FR-502)")
def facility_detail(hist_id: int):
    with get_engine().connect() as c:
        return svc.facility_detail(c, hist_id)
