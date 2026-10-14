"""요청·계산 파라미터 해석 — 식별자 형식, 페이지 범위. 규칙에 어긋나면 Invalid."""
from __future__ import annotations

import math
import uuid
from typing import Any

from atlas.domain.errors import Invalid

MAX_SIZE = 200
MAX_PAGE = 100_000   # OFFSET 이 bigint 를 넘지 않게 (그 이상은 의미 없는 페이지)


def ascii_digits(v: str | None) -> bool:
    """0-9 로만 — str.isdigit 와 정규식 \\d 는 아랍·전각·위첨자 숫자도 받고, $ 는 끝 줄바꿈도 받음."""
    return bool(v) and v.isascii() and v.isdigit()


def parse_region_code(v: str | None, lengths: tuple[int, ...] = (2, 5), message: str | None = None) -> str:
    """지역 코드(시도 2자리·시군구 5자리) — 검사를 여기 한 곳에서. 예전에는 7곳에 따로 있어 갈라졌음(같은 '١١'에 400·404·200)."""
    if not ascii_digits(v) or len(v) not in lengths:
        raise Invalid(message or f"지역 코드는 {'·'.join(f'{n}자리' for n in lengths)} 숫자(0-9)입니다.")
    return v


def parse_uuid(v: str | None, what: str = "calcRunId") -> uuid.UUID | None:
    if v in (None, ""):
        return None
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise Invalid(f"{what} 형식이 잘못되었습니다: {v}") from e


def page_params(page: int, size: int, cap: int = MAX_SIZE) -> tuple[int, int, int]:
    if not 1 <= page <= MAX_PAGE:
        raise Invalid(f"page 는 1~{MAX_PAGE} 이어야 합니다.")
    if not 1 <= size <= cap:
        raise Invalid(f"size 는 1~{cap} 이어야 합니다.")
    return page, size, (page - 1) * size


# 계산 설정(mart.calc_run.params) 해석 — 계산·What-if·배치 제안·개요가 같은 기준을 쓰게
DEFAULT_FAR_KM = 2   # '먼 거리' 기본값 (calc/runner.py DEFAULT_PARAMS 의 farKm)


def far_meters(params: dict[str, Any]) -> float:
    """'먼 거리' 기준(m)."""
    return float(params.get("farKm", DEFAULT_FAR_KM)) * 1000


def pick_level(params: dict[str, Any], level: int | None) -> int:
    """요청 레벨 — 생략하면 계산한 가장 세밀한 레벨. 계산하지 않은 레벨이면 Invalid."""
    levels = [int(x) for x in params.get("levels", [2])]
    lvl = level or max(levels)
    if lvl not in levels:
        raise Invalid(f"level {lvl} 은 이 calc_run 에서 계산되지 않았습니다 (가능: {levels}).")
    return lvl


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """지도 범위 'minLon,minLat,maxLon,maxLat' → 숫자 4개. 유한한 경위도이고 min < max 여야 함 — 뒤집힌 범위는 PostGIS 가
    바로잡아 주므로 그대로 두면 넓이 상한 검사(음수 넓이)를 피했고, NaN 은 오류 없이 빈 목록이 됐음."""
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
    except ValueError as e:
        raise Invalid("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or not (-180 <= x1 < x2 <= 180 and -90 <= y1 < y2 <= 90):
        raise Invalid("bbox 는 경도 -180~180·위도 -90~90 안에서 min 이 max 보다 작아야 합니다.")
    return x1, y1, x2, y2
