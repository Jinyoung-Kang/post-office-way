"""도메인 규칙 — 금융 가능 판정(R-FIN-01), 우편집중국 판정, 변경 감지 해시.

규칙 해석이 바뀌면 RULE_VERSION 을 올리고 새 calc_run 으로 재계산합니다(이전 결과 보존).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from atlas.domain.timeparse import parse_range

RULE_VERSION = "R-FIN-01/v1"

POST_DIV_LABEL = {0: "총괄국", 1: "소속 우체국", 2: "우체통", 3: "365코너", 4: "무인창구", 5: "우표판매소"}
POST_OFFICE_DIVS = (0, 1)


def is_center(area_code: str | None, name: str | None) -> bool:
    """우편집중국 여부 — 명세 "c는 우편집중국입니다." (지역코드 접두 c) 또는 이름에 '우편집중국'."""
    if area_code and area_code.strip().lower().startswith("c"):
        return True
    return bool(name and "우편집중국" in name)


def fin_available(post_div: int | None, finance_time: str | None, center: bool) -> bool:
    """R-FIN-01 — 금융 가능 시설 판정.

    1. post_div ∈ {0, 1} (총괄국·소속 우체국)
    2. finance_time 이 HH:MM~HH:MM 형식
    3. finance_time ≠ 00:00~00:00  (확인 필요 — U-5)
    4. 우편집중국이 아님
    """
    if post_div not in POST_OFFICE_DIVS or center:
        return False
    tr = parse_range(finance_time)
    return tr is not None and not tr.is_zero


HASH_FIELDS = ("post_div", "name", "addr", "tel", "lat", "lon", "post_time", "finance_time",
               "lunch_yn", "lunch_time", "post365_yn", "area_code", "mod_dt")


def row_hash(rec: dict[str, Any]) -> str:
    """업무 필드를 정규화한 뒤 SHA-256. 좌표는 소수 6자리(≈0.1m)로 반올림해 부동소수 흔들림 제거."""
    norm: dict[str, Any] = {}
    for f in HASH_FIELDS:
        v = rec.get(f)
        if f in ("lat", "lon") and v is not None:
            v = f"{float(v):.6f}"
        elif isinstance(v, str):
            v = " ".join(v.split())
        elif v is not None:
            v = str(v)
        norm[f] = v
    return hashlib.sha256(json.dumps(norm, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
