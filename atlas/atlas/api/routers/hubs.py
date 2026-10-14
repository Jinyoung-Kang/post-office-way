from __future__ import annotations

from fastapi import APIRouter, Query

from atlas.core.db import get_engine
from atlas.features import hubs as svc

router = APIRouter(tags=["hubs"])


@router.get("/hubs/summary", summary="⑦ 생활 거점 — 전국 합계·자료 시점·상위 시군구")
def hubs_summary(calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.summary(c, calcRunId)


@router.get("/hubs/facilities", summary="⑦ 우체국별 대체 불가능성 순위 (닫히면 생활 거점이 사라지는 인구)")
def hubs_facilities(sido: str | None = Query(None, pattern=r"^[0-9]{2}$"),
                    sort: str = Query("soleHub", pattern="^(soleHub|soleFin|served)$"),
                    page: int = 1, size: int = 20, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.facilities(c, calcRunId, sido, sort, page, size)


@router.get("/care", summary="⑦ 약국·의원 지도 레이어 (bbox 필수)")
def care_layer(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
               kind: str = Query("all", pattern="^(all|PHARMACY|CLINIC)$"),
               holidayOnly: bool = False, size: int = 3000):
    with get_engine().connect() as c:
        return svc.care_places(c, bbox, kind, holidayOnly, size)
