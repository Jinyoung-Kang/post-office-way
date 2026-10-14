from __future__ import annotations

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response

from atlas.core.db import get_engine
from atlas.features.banks import service as svc

PLACE_ID = Path(..., pattern=r"^[A-Za-z0-9_-]{1,20}$")

router = APIRouter(prefix="/banks", tags=["banks"])


@router.get("", summary="④ 은행·금고 지점 (지도 레이어, bbox 필수)")
def list_banks(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"), atm: bool = False, size: int = 3000):
    with get_engine().connect() as c:
        return svc.places_in_bbox(c, bbox, atm, size)


@router.get("/impact", summary="① 은행 지점 폐쇄 영향평가 — 순위·등급별 개수 (시도·시군구·등급 필터)")
def impact_list(sido: str | None = Query(None, pattern=r"^[0-9]{2}$"), sgg: str | None = Query(None, pattern=r"^[0-9]{5}$"),
                grade: str | None = Query(None, pattern="^(HIGH|MID|LOW)$"),
                sort: str = Query("lost", pattern="^(lost|catch|aged|walk|far)$"),
                page: int = 1, size: int = 20, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.list_impact(c, calcRunId, sido, sgg, grade, sort, page, size)


@router.get("/impact/{place_id}", summary="① 은행 지점 하나 — 이용 주민·대체 창구(같은 은행·다른 은행·우체국)·거리대별 인구")
def impact_detail(place_id: str = PLACE_ID, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.detail(c, place_id, calcRunId)


@router.get("/impact/{place_id}/geojson", summary="① 이 지점이 가장 가까운 은행 지점인 집계구 (닫히면 대체 창구까지 거리)")
def impact_geojson(place_id: str = PLACE_ID, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return Response(svc.catchment_geojson(c, place_id, calcRunId), media_type="application/json")
