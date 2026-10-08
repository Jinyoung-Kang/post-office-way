"""도메인 오류 — 규칙·조회 계층은 HTTP 를 모르고 이 오류만 던짐. HTTP 상태로 바꾸는 곳은 api/errors.py 한 곳."""
from __future__ import annotations


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Invalid(DomainError):
    """입력이 규칙에 맞지 않음 (API 400)."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(code, message)


class NotFound(DomainError):
    """찾는 대상이 없음 (API 404)."""


class Conflict(DomainError):
    """지금 상태에서는 할 수 없음 — 예: 아직 끝나지 않은 계산 실행 (API 409)."""
