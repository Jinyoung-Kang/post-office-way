"""시간 — 서비스 기준 시각은 한국 표준시(KST). DB 의 예보·휴일 시각은 KST 벽시계(naive)로 저장합니다."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)
