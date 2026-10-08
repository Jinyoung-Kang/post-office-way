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


# SQLAlchemy 예외 문자열 끝에 붙는 SQL 원문·바인드 값(사용자 입력일 수 있음)·안내 링크
# (보통 줄바꿈 뒤에 오지만, 한 줄로 합쳐 저장된 오류에서도 떼도록 공백 전체를 봄)
_SQLA_TAIL = re.compile(r"\s*(?:\[SQL:|\[parameters:|\(Background on this error).*", re.S)


def brief_error(s: str, limit: int = 300) -> str:
    """오류 로그용 한 줄 — SQL 원문·바인드 값을 떼고 공백을 합친 뒤 limit 자로 자름 (전체 내용은 traceId 로 서버 로그에서)."""
    s = " ".join(_SQLA_TAIL.sub("", s or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def known_secrets() -> list[str]:
    """설정에 있는 키·비밀번호 원문 — 오류 문자열에 남았으면 지우는 마지막 안전망용."""
    from atlas.core.config import get_settings

    s = get_settings()
    vals = [s.post_service_key, s.sgis_consumer_key, s.sgis_consumer_secret, s.kakao_rest_api_key,
            s.kosis_api_key, s.data_go_kr_key, s.admin_token, s.api_db_password]
    # API 컨테이너는 외부 키 대신 표시값('set')만 받음 — 짧은 값까지 가리면 오류 문장의 'reset' 같은 낱말이 깨짐
    return [v for v in vals if v and len(v) >= 8]


def safe_error(s: str | None, limit: int = 1000) -> str | None:
    """실행 기록(collect_run·calc_run·walk_run·job)에 저장하는 오류 — 키를 가리고 SQL 원문·바인드 값을 뗀 한 줄.
    이 값은 공개 목록(/meta/*-runs·jobs)에 그대로 나가므로 원문은 서버 로그(traceId·log.exception)에만 (S6)."""
    if not s:
        return s
    return brief_error(mask_secrets_in(mask_text(s), known_secrets()), limit)

