from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from atlas.api.common import bad_request
from atlas.api.services import calendar as svc
from atlas.core.clock import now_kst
from atlas.core.db import get_engine

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", summary="영업일 달력 — 주말·공휴일(특일 정보) 창구 휴무, 3일 이상 연휴 표시")
def calendar(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), days: int = 14):
    if not 1 <= days <= 62:
        raise bad_request("days 는 1~62 입니다.")
    d0 = date.fromisoformat(start) if start else now_kst().date()
    with get_engine().connect() as c:
        return {"today": now_kst().date().isoformat(), "hasCalendar": svc.has_calendar(c, d0),
                "items": svc.days(c, d0, days)}
