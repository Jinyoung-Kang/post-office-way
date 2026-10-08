"""영업일 달력 조회 — 공공기관 휴일(mart.holiday) + 주말 → 우체국 창구 휴무 판정 (규칙은 domain/calendar.py)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.domain.calendar import day_status, holiday_run


def holidays(c: Connection, start: date, end: date) -> dict[date, str]:
    return {r[0]: r[1] for r in c.execute(text("""SELECT locdate, name FROM mart.holiday
                                                   WHERE is_holiday AND locdate BETWEEN :a AND :b"""),
                                          {"a": start, "b": end})}


def has_calendar(c: Connection, d: date) -> bool:
    """그 해 공휴일 자료가 있는지 — 없으면 주말만 휴무로 판정하고 화면에 알림."""
    return bool(c.execute(text("SELECT 1 FROM mart.holiday WHERE extract(year FROM locdate) = :y LIMIT 1"),
                          {"y": d.year}).first())


def days(c: Connection, start: date, n: int) -> list[dict[str, Any]]:
    hol = holidays(c, start - timedelta(days=10), start + timedelta(days=n + 10))
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        st = day_status(d, hol)
        run = holiday_run(d, hol)
        st["runDays"] = len(run) if len(run) >= 3 else None      # 3일 이상 이어지는 휴무만 '연휴'
        out.append(st)
    return out
