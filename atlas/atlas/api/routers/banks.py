from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from atlas.api.common import bad_request, jsonable
from atlas.core.db import get_engine

router = APIRouter(prefix="/banks", tags=["banks"])


@router.get("", summary="④ 은행·금고 지점 (지도 레이어, bbox 필수)")
def list_banks(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"), atm: bool = False, size: int = 3000):
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
    except ValueError as e:
        raise bad_request("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
    if not 1 <= size <= 5000:
        raise bad_request("size 는 1~5000 입니다.")
    kinds = ["BRANCH", "ATM"] if atm else ["BRANCH"]
    with get_engine().connect() as c:
        rows = c.execute(text("""
            SELECT place_id, name, category, kind, addr, ST_Y(geom) AS lat, ST_X(geom) AS lon, last_seen
              FROM mart.bank_place
             WHERE geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326) AND kind = ANY(CAST(:k AS text[]))
             ORDER BY place_id LIMIT :n"""), {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "k": kinds, "n": size}).mappings().all()
    return {"items": [jsonable({"placeId": r["place_id"], "name": r["name"], "category": r["category"], "kind": r["kind"],
                                "addr": r["addr"], "lat": r["lat"], "lon": r["lon"], "lastSeen": r["last_seen"]})
                      for r in rows], "total": len(rows)}
