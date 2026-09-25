"""공공데이터포털(apis.data.go.kr) 공통 — 기상청·에어코리아는 같은 일반 인증키(serviceKey)와 같은 응답 틀을 씁니다.

키는 raw 원문 저장 전에 마스킹됩니다(serviceKey). 키 미등록·한도 초과처럼 계속 호출해도 소용없는 오류면
DataGoStop 을 던져 수집을 멈춥니다(이미 받은 결과는 남음).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from atlas.collector.http import Fetcher
from atlas.core.config import get_settings

# 키 미등록·만료·한도 초과 — 재시도해도 같은 결과
STOP_CODES = {"20", "22", "30", "31", "32", "33"}
_XML_CODE = re.compile(r"<returnReasonCode>(\d+)</returnReasonCode>")
_XML_MSG = re.compile(r"<(?:returnAuthMsg|errMsg)>([^<]+)</")


class DataGoStop(RuntimeError):
    """인증 실패·한도 초과 — 계속 호출해도 소용없는 오류."""


def require_key() -> str:
    key = get_settings().data_go_kr_key
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 가 비어 있습니다 (.env 에 공공데이터포털 일반 인증키를 넣어 주세요).")
    return key


def make_fetcher(run_id: uuid.UUID, source: str) -> Fetcher:
    return Fetcher(run_id, source, secrets=[require_key()], gzip_threshold=0)


def _error_of(status: int | None, body: str) -> tuple[str | None, str]:
    """(결과코드, 메시지) — JSON 헤더, XML 오류 봉투, 게이트웨이 JSON 오류 모두 처리."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        data = None
    if isinstance(data, dict):
        if "response" in data:
            h = data["response"].get("header") or {}
            return str(h.get("resultCode", "")), str(h.get("resultMsg", ""))
        env = (data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader") or {}
        if env:
            return str(env.get("returnReasonCode", "")), str(env.get("errMsg") or env.get("returnAuthMsg") or "")
    code, msg = _XML_CODE.search(body or ""), _XML_MSG.search(body or "")
    if code or msg:
        return (code.group(1) if code else None), (msg.group(1) if msg else "")
    return (None, f"HTTP {status}") if status and status >= 400 else (None, "")


def call(fetcher: Fetcher, url: str, params: dict[str, Any], source: str) -> dict[str, Any] | None:
    """정상이면 response.body(dict), 결과 없음(03)이면 빈 dict, 그 밖의 실패는 None, 멈춰야 하면 DataGoStop."""
    res = fetcher.get(url, {**params, "serviceKey": require_key()}, source=source)
    time.sleep(get_settings().datago_call_delay_ms / 1000)
    code, msg = _error_of(res.status, res.body)
    if code in STOP_CODES or res.status in (401, 403) or "SERVICE_KEY" in (msg or ""):
        raise DataGoStop(f"{source} 중단 (코드 {code or res.status}): {msg[:120]}")
    if code == "03":
        return {}
    if not res.ok or code not in ("00", "0"):
        return None
    return json.loads(res.body)["response"].get("body") or {}


def items_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    """기상청은 body.items.item[], 에어코리아는 body.items[]."""
    items = (body or {}).get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    return items if isinstance(items, list) else [items]
