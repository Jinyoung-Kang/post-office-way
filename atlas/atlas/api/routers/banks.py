from __future__ import annotations

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response
from sqlalchemy import text

from atlas.core.serial import jsonable
from atlas.domain.errors import Invalid
from atlas.api.services import bank_impact as impact
from atlas.core.db import get_engine

PLACE_ID = Path(..., pattern=r"^[A-Za-z0-9_-]{1,20}$")

router = APIRouter(prefix="/banks", tags=["banks"])


@router.get("", summary="④ 은행·금고 지점 (지도 레이어, bbox 필수)")
def list_banks(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"), atm: bool = False, size: int = 3000):
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
    except ValueError as e:
        raise Invalid("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
    if not 1 <= size <= 5000:
        raise Invalid("size 는 1~5000 입니다.")
    with get_engine().connect() as c:
        # 대면 지점은 '지금 영업 중'으로 보는 목록(마지막 전수 수집 기준), ATM 은 수집한 그대로
        rows = c.execute(text("""
            SELECT place_id, name, category, brand, kind, addr, ST_Y(geom) AS lat, ST_X(geom) AS lon, last_seen FROM (
                SELECT place_id, name, category, brand, 'BRANCH' AS kind, addr, geom, last_seen FROM mart.bank_branch_current
                UNION ALL
                SELECT place_id, name, category, brand, kind, addr, geom, last_seen FROM mart.bank_place
                 WHERE kind = 'ATM' AND CAST(:atm AS boolean)) b
             WHERE geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)
             ORDER BY place_id LIMIT :n"""), {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "atm": atm, "n": size}).mappings().all()
    return {"items": [jsonable({"placeId": r["place_id"], "name": r["name"], "category": r["category"], "brand": r["brand"],
                                "kind": r["kind"], "addr": r["addr"], "lat": r["lat"], "lon": r["lon"], "lastSeen": r["last_seen"]})
                      for r in rows], "total": len(rows)}


@router.get("/impact", summary="① 은행 지점 폐쇄 영향평가 — 순위·등급별 개수 (시도·시군구·등급 필터)")
def impact_list(sido: str | None = Query(None, pattern=r"^\d{2}$"), sgg: str | None = Query(None, pattern=r"^\d{5}$"),
                grade: str | None = Query(None, pattern="^(HIGH|MID|LOW)$"),
                sort: str = Query("lost", pattern="^(lost|catch|aged|walk|far)$"),
                page: int = 1, size: int = 20, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return impact.list_impact(c, calcRunId, sido, sgg, grade, sort, page, size)


@router.get("/impact/{place_id}", summary="① 은행 지점 하나 — 이용 주민·대체 창구(같은 은행·다른 은행·우체국)·거리대별 인구")
def impact_detail(place_id: str = PLACE_ID, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return impact.detail(c, place_id, calcRunId)


@router.get("/impact/{place_id}/geojson", summary="① 이 지점이 가장 가까운 은행 지점인 집계구 (닫히면 대체 창구까지 거리)")
def impact_geojson(place_id: str = PLACE_ID, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return Response(impact.catchment_geojson(c, place_id, calcRunId), media_type="application/json")
