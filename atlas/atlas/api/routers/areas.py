from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from atlas.api.services import areas as svc
from atlas.core.db import get_engine

router = APIRouter(prefix="/areas", tags=["areas"])


@router.get("", summary="지역 목록 + 지표·순위·백분위 (FR-304)")
def list_areas(level: int = 2, metric: str = "ACCESS_GAP_SCORE", parent: str | None = None,
               calcRunId: str | None = None, sort: str = "desc", page: int = 1, size: int = 50):
    with get_engine().connect() as c:
        return svc.list_areas(c, level, metric, parent, calcRunId, sort, page, size)


@router.get("/geojson", summary="단계구분도용 FeatureCollection (FR-501, 캐시)")
def areas_geojson(level: int = Query(..., description="2 시군구 · 3 읍면동"),
                  metric: str = Query(..., description="metric_def 코드"),
                  parent: str | None = Query(None, description="상위 adm_cd (level=3 이면 필수)"),
                  calcRunId: str | None = None,
                  simplify: float | None = Query(None, description="단순화 허용오차(m). 기본 level2=200, level3=50")):
    with get_engine().connect() as c:
        body = svc.geojson(c, level, metric, parent, calcRunId, simplify)
    return Response(body, media_type="application/geo+json; charset=utf-8")


@router.get("/{adm_cd}", summary="지역 상세 — 인구·지표·최근접 3개 (FR-502)")
def area_detail(adm_cd: str, calcRunId: str | None = None):
    with get_engine().connect() as c:
        return svc.area_detail(c, adm_cd, calcRunId)
