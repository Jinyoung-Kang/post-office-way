"""카카오 REST 공통 — 로컬(주소·장소 검색)과 모빌리티(길찾기)는 같은 REST 키를 `Authorization: KakaoAK` 헤더로 씁니다.

키는 헤더로만 보내므로 raw 원문(URL·파라미터)에 남지 않습니다. 쿼터 초과(429)나 인증 실패(401/403)면
KakaoStop 을 던져 수집을 멈추고, 이미 받은 결과는 캐시에 남아 다음 실행에 이어서 씁니다.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any

from atlas.collector.http import Fetcher
from atlas.core.config import get_settings


class KakaoStop(RuntimeError):
    """쿼터 초과·인증 실패 — 계속 호출해도 소용없는 오류."""


def require_key() -> str:
    key = get_settings().kakao_rest_api_key
    if not key:
        raise RuntimeError("KAKAO_REST_API_KEY 가 비어 있습니다 (.env 확인).")
    return key


def make_fetcher(run_id: uuid.UUID, source: str) -> Fetcher:
    key = require_key()
    return Fetcher(run_id, source, secrets=[key], headers={"Authorization": f"KakaoAK {key}"}, gzip_threshold=0)


def call(fetcher: Fetcher, url: str, params: dict[str, Any], source: str) -> dict[str, Any] | None:
    """성공이면 JSON, 결과 없음 계열(4xx 중 400)이면 None, 멈춰야 하면 KakaoStop."""
    res = fetcher.get(url, params, source=source)
    time.sleep(get_settings().kakao_call_delay_ms / 1000)
    if res.status in (401, 403, 429):
        raise KakaoStop(f"카카오 API 중단 HTTP {res.status}: {res.body[:200]}")
    if not res.ok:
        return None
    try:
        return json.loads(res.body)
    except json.JSONDecodeError:
        return None


_PAREN = re.compile(r"\s*\([^)]*\)\s*")
_UNIT = re.compile(r"^(B?\d+F|B\d+|\d+층|지하\d*층?|[\d~\-]+호|\d+동)$", re.I)


def clean_addr(addr: str | None) -> str:
    """주소 검색에 방해되는 부가정보를 뗌 — 괄호, 첫 쉼표 뒤(상세주소·☎ 전화), 층·호수 낱말.
    '서울 중구 을지로 154-2 (을지로4가), ☎ 02-…' → '서울 중구 을지로 154-2' / '… 언주로 508 1F(역삼동)' → '… 언주로 508'"""
    s = _PAREN.sub(" ", addr or "").split(",")[0]
    words = [w for w in s.split() if not _UNIT.match(w)]
    return " ".join(words).strip()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


NON_RETAIL = ("한국은행", "한국산업은행", "한국수출입은행", "외국은행")


def classify_bank(name: str, category: str) -> str | None:
    """BK9 장소 → 'BRANCH' | 'ATM' | None(우체국 관련은 이미 우체국 데이터로 셈, 정책·중앙·외국은행은 개인 창구 아님)."""
    n, cat = name or "", category or ""
    if "우체국" in n or "우체국" in cat:
        return None
    if any(x in cat for x in NON_RETAIL):   # 개인 대면 창구가 아닌 정책·중앙·외국은행
        return None
    if cat.endswith("ATM") or "ATM" in n.upper() or "365" in n or "자동화" in n or "무인" in n:
        return "ATM"
    return "BRANCH"
