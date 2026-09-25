"""작업 스케줄 — 워커가 매 순환마다 due() 를 보고, 지금이 예정 시각 뒤 WINDOW 안이면 슬롯 키로 한 번만 넣습니다.

워커가 꺼져 있던 동안 지난 슬롯은 몰아서 실행하지 않습니다(예보처럼 지난 자료는 의미가 없음).
그룹은 .env ATLAS_SCHEDULE 로 켭니다 (기본 weather,holidays,care — post 는 호출이 많아 선택).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

WINDOW = timedelta(minutes=30)


@dataclass(frozen=True)
class Entry:
    kind: str
    group: str
    times: tuple[tuple[int, int], ...]          # (시, 분) KST
    weekdays: tuple[int, ...] | None = None     # 0=월 … 6=일, None=매일
    note: str = ""


SCHEDULE: tuple[Entry, ...] = (
    Entry("kma", "weather", tuple((h, 20) for h in (2, 5, 8, 11, 14, 17, 20, 23)), note="단기예보 발표 +20분"),
    Entry("air", "weather", ((5, 30), (11, 30), (17, 30), (23, 30)), note="대기질 예보 발표 +30분"),
    Entry("holidays", "holidays", ((4, 10),), note="대체·임시공휴일 반영"),
    Entry("care", "care", ((4, 20),), weekdays=(0,), note="약국·병의원 전체 자료 (끝나면 지표 재계산)"),
    Entry("post", "post", ((3, 0),), note="우체국 시설 (끝나면 지표 재계산)"),
)


def enabled(groups: str) -> list[Entry]:
    on = {g.strip() for g in groups.split(",") if g.strip()}
    return [e for e in SCHEDULE if e.group in on or "all" in on]


def _occurrences(e: Entry, day: datetime) -> list[datetime]:
    if e.weekdays is not None and day.weekday() not in e.weekdays:
        return []
    return [day.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in e.times]


def due(now: datetime, entries: list[Entry]) -> list[tuple[str, str]]:
    """[(kind, slot)] — now 가 예정 시각 t 이후 WINDOW 안이면 slot=f'{kind}@{t:%Y-%m-%dT%H:%M}'."""
    out = []
    for e in entries:
        for day in (now - timedelta(days=1), now):
            for t in _occurrences(e, day):
                if t <= now < t + WINDOW:
                    out.append((e.kind, f"{e.kind}@{t:%Y-%m-%dT%H:%M}"))
    return out


def next_run(now: datetime, e: Entry) -> datetime | None:
    for i in range(8):
        for t in sorted(_occurrences(e, now + timedelta(days=i))):
            if t > now:
                return t
    return None


def describe(now: datetime, groups: str) -> list[dict[str, Any]]:
    on = {x.kind for x in enabled(groups)}
    return [{"kind": e.kind, "group": e.group, "enabled": e.kind in on, "note": e.note,
             "times": [f"{h:02d}:{m:02d}" for h, m in e.times],
             "weekdays": list(e.weekdays) if e.weekdays is not None else None,
             "nextRunAt": (n.isoformat() if (n := next_run(now, e)) and e.kind in on else None)} for e in SCHEDULE]
