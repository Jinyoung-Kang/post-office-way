from __future__ import annotations

from fastapi import APIRouter, Query

from atlas.api.services import visit as svc
from atlas.core.db import get_engine

router = APIRouter(prefix="/visit", tags=["visit"])


@router.get("/conditions", summary="⑥ 시군구별 방문 여건 (기상청 단기예보·에어코리아 예보 × 먼 곳 고령인구)")
def conditions(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD, 생략하면 오늘(운영 시간이 끝났으면 내일)"),
               sido: str | None = Query(None, description="시도 코드 2자리로 좁히기")):
    with get_engine().connect() as c:
        return svc.conditions(c, date, sido)


@router.get("/conditions/{adm_cd}", summary="⑥ 한 시군구(읍면동이면 상위 시군구)의 오늘~모레 방문 여건")
def area_outlook(adm_cd: str):
    with get_engine().connect() as c:
        return svc.area_outlook(c, adm_cd)
