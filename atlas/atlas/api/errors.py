"""오류 규약 — HTTP 상태 + {code, message, traceId} (설계서 6-1)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def not_found(code: str, message: str) -> ApiError:
    return ApiError(404, code, message)


def bad_request(message: str) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", message)


def _body(request: Request, code: str, message: str) -> dict:
    return {"code": code, "message": message, "traceId": getattr(request.state, "trace_id", None)}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(_body(request, "VALIDATION_ERROR", msg), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _any(request: Request, exc: Exception):
        log.exception("unhandled", extra={"traceId": getattr(request.state, "trace_id", None)})
        return JSONResponse(_body(request, "INTERNAL", "서버 내부 오류"), status_code=500)
