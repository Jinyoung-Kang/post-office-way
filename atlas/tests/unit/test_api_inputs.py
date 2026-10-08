"""입력 검증이 DB 에 가기 전에 400 을 돌려주는지 — 500(내부 오류)·오류 로그 기록이 되면 안 됨 (S8)."""
import pytest
from fastapi.testclient import TestClient

from atlas.api.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("start", ["2026-02-30", "2026-13-01", "0001-01-01", "9999-12-31"])
def test_calendar_impossible_or_extreme_dates_are_400(start):
    r = client.get("/api/v1/calendar", params={"start": start, "days": 62})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", r.text
