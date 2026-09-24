"""키 마스킹 — raw 저장·로그 전에 serviceKey / consumer_key / consumer_secret / accessToken / apiKey(KOSIS) 값을 *** 로 치환 (FR-103)."""
from __future__ import annotations

import re
from typing import Any

SENSITIVE_PARAMS = ("serviceKey", "consumer_key", "consumer_secret", "accessToken", "ServiceKey", "apiKey")
_LOWER = {p.lower() for p in SENSITIVE_PARAMS}
MASK = "***"

# 쿼리스트링·JSON 본문 모두에서 key=value / "key":"value" 형태를 잡습니다.
_QS = re.compile(r"(?i)\b(" + "|".join(SENSITIVE_PARAMS) + r")=([^&\s\"']+)")
_JSON = re.compile(r'(?i)"(' + "|".join(SENSITIVE_PARAMS) + r')"\s*:\s*"([^"]*)"')


def mask_text(s: str) -> str:
    if not s:
        return s
    s = _QS.sub(lambda m: f"{m.group(1)}={MASK}", s)
    return _JSON.sub(lambda m: f'"{m.group(1)}":"{MASK}"', s)


def mask_params(params: dict[str, Any] | None) -> dict[str, Any]:
    return {k: (MASK if k.lower() in _LOWER else v) for k, v in (params or {}).items()}


def mask_secrets_in(s: str, secrets: list[str]) -> str:
    """알려진 키 원문(인코딩된 형태 포함)이 어디든 남아 있으면 지웁니다 — 마지막 안전망."""
    from urllib.parse import quote, quote_plus

    for sec in secrets:
        if not sec:
            continue
        for form in {sec, quote(sec, safe=""), quote_plus(sec)}:
            s = s.replace(form, MASK)
    return s
