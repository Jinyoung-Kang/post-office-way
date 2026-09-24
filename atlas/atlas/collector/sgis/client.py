"""SGIS OpenAPI3 클라이언트 — accessToken 발급·캐시·만료 60초 전 재발급 (FR-201)."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from atlas.collector.http import Fetcher
from atlas.core.config import get_settings

log = logging.getLogger(__name__)
REFRESH_MARGIN_S = 60
# SGIS 오류코드: -401 = 인증 정보 없음/만료
TOKEN_ERRORS = {-401, "-401"}


class SgisError(RuntimeError):
    def __init__(self, code: Any, msg: str):
        super().__init__(f"SGIS errCd={code}: {msg}")
        self.code, self.msg = code, msg


def parse_timeout(v: Any) -> float:
    """accessTimeout — 문서는 '1970년 1월1일 0시부터 현재까지의 초'. 실제로 ms 로 오는 경우도 수용."""
    t = float(v)
    return t / 1000 if t > 1e11 else t


@dataclass
class SgisClient:
    fetcher: Fetcher
    now: Callable[[], float] = time.time
    _token: str | None = None
    _expires_at: float = 0.0
    token_issued: int = 0

    @property
    def base(self) -> str:
        return get_settings().sgis_base_url

    def token(self, force: bool = False) -> str:
        if not force and self._token and self.now() < self._expires_at - REFRESH_MARGIN_S:
            return self._token
        s = get_settings()
        if not (s.sgis_consumer_key and s.sgis_consumer_secret):
            raise RuntimeError("SGIS_CONSUMER_KEY / SGIS_CONSUMER_SECRET 이 비어 있습니다 (.env 확인).")
        res = self.fetcher.get(f"{self.base}/auth/authentication.json",
                               {"consumer_key": s.sgis_consumer_key, "consumer_secret": s.sgis_consumer_secret},
                               source="SGIS_AUTH")
        data = self._json(res.body)
        result = data.get("result") or {}
        if str(data.get("errCd", 0)) != "0" or not result.get("accessToken"):
            raise SgisError(data.get("errCd"), data.get("errMsg") or "토큰 발급 실패")
        self._token = result["accessToken"]
        self.fetcher.secrets.append(self._token)
        self._expires_at = parse_timeout(result.get("accessTimeout") or (self.now() + 3600))
        self.token_issued += 1
        return self._token

    @staticmethod
    def _json(body: str) -> dict[str, Any]:
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            raise SgisError("PARSE", f"JSON 파싱 실패: {e}") from e

    def get(self, path: str, params: dict[str, Any], source: str) -> dict[str, Any]:
        """토큰 만료 오류(-401)면 한 번 재발급 후 재시도."""
        for attempt in (1, 2):
            res = self.fetcher.get(f"{self.base}/{path}", {"accessToken": self.token(force=attempt == 2), **params},
                                   source=source)
            if not res.ok:
                raise SgisError(res.status, res.error or "HTTP 오류")
            data = self._json(res.body)
            code = data.get("errCd", 0)
            if code in TOKEN_ERRORS and attempt == 1:
                log.info("sgis token expired, refreshing")
                continue
            if str(code) != "0":
                raise SgisError(code, data.get("errMsg") or "")
            return data
        raise SgisError(-401, "토큰 재발급 후에도 인증 실패")
