from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from atlas.api.services import plan as svc
from atlas.core.db import get_engine

router = APIRouter(prefix="/plan", tags=["plan"])


class PlanRequest(BaseModel):
    scope: str = Field(..., description="시도 2자리 또는 시군구 5자리 (SGIS 코드)")
    k: int = Field(3, description=f"고를 개수 1~{svc.MAX_K}")
    weight: str = Field("aged65", description="aged65(65세 이상, KOSIS) | pop(전체 인구, SGIS)")
    level: int | None = None
    calcRunId: str | None = None


@router.post("/close", summary="⑤ 폐국 영향이 가장 작은 조합 (탐욕법)")
def close(req: PlanRequest):
    with get_engine().connect() as c:
        return svc.plan_close(c, req.scope, req.k, req.weight, req.level, req.calcRunId)


@router.post("/open", summary="⑤ 신설 효과가 가장 큰 후보지 (탐욕 p-median 근사)")
def open_(req: PlanRequest):
    with get_engine().connect() as c:
        return svc.plan_open(c, req.scope, req.k, req.weight, req.level, req.calcRunId)
