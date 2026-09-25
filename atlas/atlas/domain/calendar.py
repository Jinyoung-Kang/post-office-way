"""영업일 달력 — 토·일과 공공기관 휴일(한국천문연구원 특일 isHoliday=Y)이면 우체국 창구 휴무로 봅니다.

우체국 365코너(ATM)·무인창구와 공휴일 진료시간이 등록된 약국·의원은 휴무일에도 쓸 수 있는 생활 거점입니다.
"""
from __future__ import annotations

from datetime import date
from typing import Any

WEEKDAY_KO = "월화수목금토일"


def day_status(d: date, holidays: dict[date, str]) -> dict[str, Any]:
    """{date, weekday, closed, reason} — reason 은 공휴일 이름 또는 '토요일'·'일요일'."""
    name = holidays.get(d)
    weekend = d.weekday() >= 5
    reason = name or (f"{WEEKDAY_KO[d.weekday()]}요일" if weekend else None)
    return {"date": d.isoformat(), "weekday": WEEKDAY_KO[d.weekday()], "closed": bool(name or weekend),
            "holiday": name, "reason": reason}


def holiday_run(d: date, holidays: dict[date, str]) -> list[date]:
    """d 를 포함한 연속 휴무일(주말·공휴일) 구간 — '연휴' 길이 표시에 씀. d 가 영업일이면 빈 목록."""
    from datetime import timedelta

    if not day_status(d, holidays)["closed"]:
        return []
    lo = hi = d
    while day_status(lo - timedelta(days=1), holidays)["closed"]:
        lo -= timedelta(days=1)
    while day_status(hi + timedelta(days=1), holidays)["closed"]:
        hi += timedelta(days=1)
    return [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
