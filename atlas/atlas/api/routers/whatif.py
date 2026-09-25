from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from atlas.api.services import whatif as svc
from atlas.core.db import get_engine

router = APIRouter(prefix="/whatif", tags=["whatif"])


class WhatIfRequest(BaseModel):
    calcRunId: str | None = None
    removeHistIds: list[int] = Field(..., description="제외할 시설 histId 1~5개")
    level: int | None = Field(None, description="분석 레벨 (생략 시 계산된 가장 세밀한 레벨)")


@router.post("", summary="시설 제외(문 닫음 가정) 시뮬레이션 (FR-401)")
def create(req: WhatIfRequest):
    with get_engine().begin() as c:
        return svc.run_whatif(c, req.calcRunId, req.removeHistIds, req.level)


@router.get("/{scenario_id}", summary="What-if 결과 재조회 (FR-402)")
def get(scenario_id: str):
    with get_engine().connect() as c:
        return svc.get_scenario(c, scenario_id)


@router.get("/{scenario_id}/geojson", summary="영향 지역 폴리곤 (FR-503 지도 오버레이)")
def geojson(scenario_id: str):
    with get_engine().connect() as c:
        return svc.scenario_geojson(c, scenario_id)
