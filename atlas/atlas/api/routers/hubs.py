from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from atlas.api.common import bad_request, jsonable
from atlas.api.services import hubs as svc
from atlas.core.db import get_engine

router = APIRouter(tags=["hubs"])


@router.get("/hubs/summary", summary="⑦ 생활 거점 — 전국 합계·자료 시점·상위 시군구")
def hubs_summary(calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.summary(c, calcRunId)


@router.get("/hubs/facilities", summary="⑦ 우체국별 대체 불가능성 순위 (닫히면 생활 거점이 사라지는 인구)")
def hubs_facilities(sido: str | None = Query(None, pattern=r"^\d{2}$"),
                    sort: str = Query("soleHub", pattern="^(soleHub|soleFin|served)$"),
                    page: int = 1, size: int = 20, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.facilities(c, calcRunId, sido, sort, page, size)


@router.get("/care", summary="⑦ 약국·의원 지도 레이어 (bbox 필수)")
def care_layer(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
               kind: str = Query("all", pattern="^(all|PHARMACY|CLINIC)$"),
               holidayOnly: bool = False, size: int = 3000):
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
    except ValueError as e:
        raise bad_request("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
    if not 1 <= size <= 5000:
        raise bad_request("size 는 1~5000 입니다.")
    if (x2 - x1) * (y2 - y1) > 4:   # 약 200km × 200km 넘는 범위는 너무 많음 — 확대해서 보도록
        raise bad_request("범위가 너무 넓습니다. 지도를 더 확대하세요.")
    with get_engine().connect() as c:
        rows = c.execute(text("""
            SELECT hpid, kind, div_name, name, addr, open_holiday, open_sunday, hours, ST_Y(geom) AS lat, ST_X(geom) AS lon
              FROM mart.care_place
             WHERE geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)
               AND (CAST(:k AS text) = 'all' OR kind = CAST(:k AS text)) AND (NOT :h OR open_holiday)
             ORDER BY hpid LIMIT :n"""), {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "k": kind, "h": holidayOnly,
                                          "n": size}).mappings().all()
    return {"items": [jsonable({"id": r["hpid"], "kind": r["kind"], "divName": r["div_name"], "name": r["name"],
                                "addr": r["addr"], "openHoliday": r["open_holiday"], "openSunday": r["open_sunday"],
                                "hours": r["hours"], "lat": r["lat"], "lon": r["lon"]}) for r in rows],
            "total": len(rows)}
