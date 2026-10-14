"""오류 규약 — HTTP 상태 + {code, message, traceId} (설계서 6-1)."""
from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from atlas.domain.errors import Conflict, DomainError, Invalid, NotFound

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# 도메인 오류 → HTTP 상태. 서비스·조회 계층은 상태 코드를 모름
_DOMAIN_STATUS: dict[type[DomainError], int] = {Invalid: 400, NotFound: 404, Conflict: 409}


def _body(request: Request, code: str, message: str) -> dict:
    return {"code": code, "message": message, "traceId": getattr(request.state, "trace_id", None)}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=_DOMAIN_STATUS.get(type(exc), 400))

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(_body(request, "VALIDATION_ERROR", msg), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED",
                413: "PAYLOAD_TOO_LARGE"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)

    # 안전망: 입력값 때문에 DB 가 거부한 경우(숫자 범위 초과·형식 오류)는 서버 오류가 아니라 잘못된 요청 (fuzz 로 찾은 버그)
    from sqlalchemy.exc import DataError

    @app.exception_handler(DataError)
    async def _data(request: Request, exc: DataError):
        log.warning("db data error", extra={"traceId": getattr(request.state, "trace_id", None),
                                            "path": request.url.path, "error": str(exc.orig)[:200]})
        return JSONResponse(_body(request, "VALIDATION_ERROR", "입력값이 허용 범위나 형식을 벗어났습니다."), status_code=400)

    @app.exception_handler(Exception)
    async def _any(request: Request, exc: Exception):
        tid = getattr(request.state, "trace_id", None)
        log.exception("unhandled", extra={"traceId": tid})
        # 동기 DB 쓰기 — 이벤트 루프에서 바로 부르면 DB 가 느릴 때 이 워커의 모든 요청이 멈춤
        await run_in_threadpool(record, tid, request.method, request.url.path, exc)
        return JSONResponse(_body(request, "INTERNAL", "서버 내부 오류"), status_code=500)


# 처리하지 못한 예외 기록의 시간당 상한(전체) — 공개 경로에 500 버그가 생겨도 오류 로그가 범람해 실제 오류를 덮지 않게.
# 넘으면 서버 로그(traceId)에만 남음. Redis 가 없으면 프로세스 안에서 셈
APP_ERROR_HOURLY_MAX = 300
_local = {"hour": None, "n": 0}
_lock = threading.Lock()


def _allow_record() -> bool:
    from atlas.core import cache

    hour = int(time.time() // 3600)
    n = cache.incr(f"apperr:hour:{hour}", ttl=3600)
    if n is None:
        with _lock:
            if _local["hour"] != hour:
                _local.update(hour=hour, n=0)
            _local["n"] += 1
            n = _local["n"]
    return n <= APP_ERROR_HOURLY_MAX


def record(trace_id: str | None, method: str, path: str, exc: BaseException) -> None:
    """처리하지 못한 예외를 ops.app_error 에 남김 — 실패해도(DB 장애 등) 응답에는 영향 없음. 키는 마스킹."""
    if not _allow_record():
        log.warning("app_error record dropped (hourly cap)", extra={"traceId": trace_id, "path": path[:200]})
        return
    try:
        from sqlalchemy import text

        from atlas.core.db import get_engine
        from atlas.core.masking import brief_error, mask_text

        with get_engine().begin() as c:
            c.execute(text("""INSERT INTO ops.app_error (source, trace_id, method, path, error_type, message)
                              VALUES ('api', :t, :m, :p, :e, :msg)"""),
                      {"t": trace_id, "m": method, "p": path[:500], "e": type(exc).__name__,
                       "msg": brief_error(mask_text(str(exc)), 1000)})
    except Exception:  # noqa: BLE001 — 오류 기록 실패가 또 오류를 만들지 않게
        log.warning("app_error record failed")
