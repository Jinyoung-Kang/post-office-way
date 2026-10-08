"""요청·계산 파라미터 해석 — 식별자 형식, 페이지 범위. 규칙에 어긋나면 Invalid."""
from __future__ import annotations

import uuid

from atlas.domain.errors import Invalid

MAX_SIZE = 200
MAX_PAGE = 100_000   # OFFSET 이 bigint 를 넘지 않게 (그 이상은 의미 없는 페이지)


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
