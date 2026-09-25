"""운영·금융·점심 시간 문자열 파서.

원문은 그대로 보존하고(stg), 여기서는 형식 판정과 정규화만 합니다.
허용 예: "09:00~18:00", "9:00 ~ 18:00", "09:00-18:00", "0900~1800"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RANGE = re.compile(
    r"^\s*(\d{1,2})\s*:?\s*(\d{2})\s*[~\-–〜]\s*(\d{1,2})\s*:?\s*(\d{2})\s*$"
)


@dataclass(frozen=True)
class TimeRange:
    start_min: int
    end_min: int

    @property
    def is_zero(self) -> bool:
        """00:00~00:00 — 명세 예시에서 우편취급국이 갖는 값 (R-FIN-01 에서 '금융 미제공'으로 해석)."""
        return self.start_min == 0 and self.end_min == 0

    @property
    def start_str(self) -> str:
        return f"{self.start_min // 60:02d}:{self.start_min % 60:02d}"

    @property
    def end_str(self) -> str:
        return f"{self.end_min // 60:02d}:{self.end_min % 60:02d}"

    def fmt(self) -> str:
        return f"{self.start_min // 60:02d}:{self.start_min % 60:02d}~{self.end_min // 60:02d}:{self.end_min % 60:02d}"


def parse_range(s: str | None) -> TimeRange | None:
    """HH:MM~HH:MM 형식이면 TimeRange, 아니면 None. 시·분 범위도 검사합니다."""
    if s is None:
        return None
    m = _RANGE.match(s)
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if not (0 <= h1 <= 24 and 0 <= h2 <= 24 and 0 <= m1 < 60 and 0 <= m2 < 60):
        return None
    if (h1 == 24 and m1) or (h2 == 24 and m2):
        return None
    return TimeRange(h1 * 60 + m1, h2 * 60 + m2)


def is_valid_format(s: str | None) -> bool:
    return parse_range(s) is not None
