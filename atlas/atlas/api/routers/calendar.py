from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from atlas.domain.errors import Invalid
from atlas.api.services import calendar as svc
from atlas.core.clock import now_kst
from atlas.core.db import get_engine

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", summary="영업일 달력 — 주말·공휴일(특일 정보) 창구 휴무, 3일 이상 연휴 표시")
def calendar(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), days: int = 14):
    if not 1 <= days <= 62:
        raise Invalid("days 는 1~62 입니다.")
    try:
        d0 = date.fromisoformat(start) if start else now_kst().date()
    except ValueError as e:                       # 형식은 맞지만 없는 날짜(2026-02-30) — 예전에는 500
        raise Invalid("start 는 실제 있는 날짜(YYYY-MM-DD)여야 합니다.") from e
    if not date(2000, 1, 1) <= d0 <= date(2100, 12, 31):   # 앞뒤 10일을 더해 보므로 양 끝은 날짜 범위 초과(500)
        raise Invalid("start 는 2000-01-01 ~ 2100-12-31 사이입니다.")
    with get_engine().connect() as c:
        return {"today": now_kst().date().isoformat(), "hasCalendar": svc.has_calendar(c, d0),
                "items": svc.days(c, d0, days)}
