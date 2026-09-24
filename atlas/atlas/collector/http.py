"""외부 호출 공통 — 지수 백오프 재시도(FR-104) + 응답 원문 raw 저장(FR-103, 키 마스킹)."""
from __future__ import annotations

import gzip
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import text

from atlas.core.config import get_settings
from atlas.core.db import begin
from atlas.core.masking import mask_params, mask_secrets_in, mask_text

log = logging.getLogger(__name__)
GZIP_THRESHOLD = 1_000_000  # 1MB 이상 원문은 gzip bytea 로 (U-4)


@dataclass
class FetchResult:
    ok: bool
    status: int | None
    body: str
    error: str | None = None
    response_id: int | None = None


@dataclass
class Fetcher:
    """run 하나 동안 쓰는 HTTP 호출기. 호출 수·오류 수를 세어 run stats 에 남깁니다(NFR-08·10)."""

    run_id: uuid.UUID
    source: str
    secrets: list[str] = field(default_factory=list)
    calls: int = 0
    errors: int = 0
    store_raw: bool = True
    headers: dict[str, str] = field(default_factory=dict)   # 인증 헤더(카카오 KakaoAK) — raw 에는 저장하지 않음
    gzip_threshold: int = GZIP_THRESHOLD                     # 이 크기 이상 원문은 gzip (대량 수집은 0 = 항상)
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        s = get_settings()
        self._client = httpx.Client(timeout=s.http_timeout_s, follow_redirects=True,
                                    headers={"User-Agent": "postal-access-atlas/0.1 (local analysis)", **self.headers})
        self._retries = s.http_retries

    def close(self) -> None:
        if self._client:
            self._client.close()

    def get(self, url: str, params: dict[str, Any], source: str | None = None,
            sleep=time.sleep) -> FetchResult:
        """최대 1 + retries 회 시도 (1s·2s·4s 대기). 마지막 결과(성공/실패)를 raw 에 저장."""
        attempt, last = 0, FetchResult(False, None, "", "not attempted")
        while attempt <= self._retries:
            if attempt:
                sleep(2 ** (attempt - 1))
            attempt += 1
            self.calls += 1
            try:
                r = self._client.get(url, params=params)
                body = r.text
                if r.status_code >= 500 or r.status_code == 429:
                    last = FetchResult(False, r.status_code, body, f"HTTP {r.status_code}")
                    continue
                last = FetchResult(r.status_code < 400, r.status_code, body,
                                   None if r.status_code < 400 else f"HTTP {r.status_code}")
                break
            except httpx.HTTPError as e:
                last = FetchResult(False, None, "", f"{type(e).__name__}: {mask_text(str(e))}")
        if not last.ok:
            self.errors += 1
            log.warning("fetch failed", extra={"source": source or self.source, "error": last.error,
                                               "params": mask_params(params)})
        if self.store_raw:
            last.response_id = self._store(url, params, last, source or self.source)
        return last

    def _store(self, url: str, params: dict[str, Any], res: FetchResult, source: str) -> int:
        masked_params = mask_params(params)
        masked_url = mask_text(f"{url}?{urlencode(masked_params)}")
        body = mask_secrets_in(mask_text(res.body or ""), self.secrets)
        if res.error and not body:
            body = json.dumps({"_fetchError": res.error}, ensure_ascii=False)
        body_text, body_gz = (None, gzip.compress(body.encode())) if len(body) > self.gzip_threshold else (body, None)
        with begin() as c:
            return c.execute(text("""INSERT INTO raw.api_response
                    (collect_run_id, source, request_url_masked, params, http_status, body, body_gz)
                    VALUES (:run, :src, :url, CAST(:p AS jsonb), :st, :b, :gz) RETURNING response_id"""),
                    {"run": self.run_id, "src": source, "url": masked_url,
                     "p": json.dumps(masked_params, ensure_ascii=False, default=str),
                     "st": res.status, "b": body_text, "gz": body_gz}).scalar_one()
