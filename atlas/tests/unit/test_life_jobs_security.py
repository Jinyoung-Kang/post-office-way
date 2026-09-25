"""⑦ 생활 거점(약국·병의원 행 해석)·영업일 달력·작업 스케줄·보안(신뢰 프록시·속도 제한 규칙)·ETag — 네트워크·DB 없음."""
import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from atlas.api.etag import ETagMiddleware, _matches
from atlas.api.security import ip_from_scope, rule_for
from atlas.api.services.calendar import business_status
from atlas.collector.datago.client import items_of
from atlas.collector.datago.holiday import parse_items as parse_holidays
from atlas.domain.calendar import day_status, holiday_run
from atlas.domain.care import hhmm, parse_hours, to_row
from atlas.jobs import registry, scheduler

FIX = Path(__file__).resolve().parents[1] / "contract" / "fixtures"


def _items(name: str):
    return items_of(json.loads((FIX / name).read_text())["response"]["body"])


@pytest.mark.parametrize("v,out", [("0900", "0900"), (900, "0900"), ("9:00", "0900"), (2330, "2330"), ("2530", "2530"),
                                   ("", None), (None, None), ("abcd", None), ("0960", None), (12345, None)])
def test_hhmm(v, out):
    assert hhmm(v) == out


def test_pharmacy_rows_mixed_types():
    rows = [to_row("PHARMACY", it) for it in _items("nmc_pharmacy_sample.json")]
    assert rows[2] is None                                        # 좌표 없음
    a, b = rows[0], rows[1]
    assert a["hours"]["1"] == ["0640", "2330"] and a["hours"]["8"] == ["0800", "2300"]
    assert a["open_holiday"] and a["open_sunday"] and a["div"] is None and a["div_name"] == "약국"
    assert not b["open_holiday"] and set(b["hours"]) == {"1", "6"}


def test_clinic_rows_filter_divisions():
    rows = [to_row("CLINIC", it) for it in _items("nmc_hospital_sample.json")]
    assert [r and r["div"] for r in rows] == ["R", None, "A", None]   # 한방병원 제외, (0,0) 좌표 제외
    assert rows[2]["open_holiday"] and rows[0]["div_name"] == "보건소"


def test_parse_hours_ignores_zero_length():
    assert parse_hours({"dutyTime1s": "0900", "dutyTime1c": "0900", "dutyTime2s": "0900"}) == {}


def test_holiday_contract_and_calendar():
    rows = parse_holidays(_items("kasi_holiday_sample.json"))
    hol = {r["d"]: r["name"] for r in rows if r["h"]}
    assert len(rows) == 6 and hol[date(2026, 9, 25)] == "추석"
    fri = day_status(date(2026, 9, 25), hol)
    assert fri["closed"] and fri["reason"] == "추석" and fri["weekday"] == "금"
    assert day_status(date(2026, 9, 29), hol) == {"date": "2026-09-29", "weekday": "화", "closed": False,
                                                   "holiday": None, "reason": None}
    assert day_status(date(2026, 9, 27), hol)["reason"] == "일요일"
    # 추석(목~토) + 일요일 → 4일 연휴, 개천절(토)~대체공휴일(월) → 3일
    assert holiday_run(date(2026, 9, 25), hol) == [date(2026, 9, 24 + i) for i in range(4)]
    assert len(holiday_run(date(2026, 10, 4), hol)) == 3 and holiday_run(date(2026, 9, 29), hol) == []


def test_business_status():
    hol = {date(2026, 9, 25): "추석"}
    assert business_status("09:00~16:30", datetime(2026, 9, 25, 10), hol)["state"] == "closed"
    assert business_status("09:00~16:30", datetime(2026, 9, 29, 8, 59), hol)["label"] == "영업 전 · 09:00 시작"
    assert business_status("09:00~16:30", datetime(2026, 9, 29, 16, 29), hol)["state"] == "open"
    assert business_status("09:00~16:30", datetime(2026, 9, 29, 16, 30), hol)["state"] == "after"
    assert business_status(None, datetime(2026, 9, 29, 10), hol)["state"] == "unknown"


def test_scheduler_due_and_next():
    entries = scheduler.enabled("weather,care")
    assert {e.kind for e in entries} == {"kma", "air", "care"}
    due = scheduler.due(datetime(2026, 9, 28, 5, 35), entries)             # 월요일
    assert ("kma", "kma@2026-09-28T05:20") in due and ("air", "air@2026-09-28T05:30") in due
    assert not any(k == "care" for k, _ in due)                            # care 는 04:20~04:50
    assert ("care", "care@2026-09-28T04:20") in scheduler.due(datetime(2026, 9, 28, 4, 49), entries)
    assert scheduler.due(datetime(2026, 9, 29, 4, 21), entries) == []      # 화요일엔 care 없음, 예보 슬롯 밖
    assert set(scheduler.due(datetime(2026, 9, 28, 23, 45), entries)) == {("kma", "kma@2026-09-28T23:20"),
                                                                           ("air", "air@2026-09-28T23:30")}
    assert scheduler.due(datetime(2026, 9, 29, 0, 5), entries) == []      # 창(30분)이 지난 슬롯은 몰아서 실행 안 함
    kma = next(e for e in entries if e.kind == "kma")
    assert scheduler.next_run(datetime(2026, 9, 28, 23, 30), kma) == datetime(2026, 9, 29, 2, 20)
    assert scheduler.enabled("") == [] and len(scheduler.enabled("all")) == len(scheduler.SCHEDULE)


def test_registry_covers_schedule_and_keys(monkeypatch):
    assert {e.kind for e in scheduler.SCHEDULE} <= set(registry.JOBS)
    from atlas.core.config import Settings

    s = Settings(_env_file=None, data_go_kr_key="")
    assert registry.get("care").missing(s) == ["DATA_GO_KR_KEY"] and registry.get("calc").missing(s) == []
    with pytest.raises(KeyError):
        registry.get("nope")


def _scope(peer: str, xff: str | None = None):
    return {"client": (peer, 1234), "headers": [(b"x-forwarded-for", xff.encode())] if xff else []}


def test_client_ip_trusts_only_private_proxies():
    assert ip_from_scope(_scope("172.18.0.5", "203.0.113.7, 172.18.0.5")) == "203.0.113.7"   # web 컨테이너 경유
    assert ip_from_scope(_scope("203.0.113.9", "1.2.3.4")) == "203.0.113.9"                  # 외부에서 위조 → 무시
    assert ip_from_scope(_scope("172.18.0.5", "not-an-ip")) == "172.18.0.5"


def test_rate_limit_rules():
    assert rule_for("POST", "/api/v1/whatif") == ("heavy", 30)
    assert rule_for("POST", "/api/v1/plan/close") == ("heavy", 30)
    assert rule_for("POST", "/api/v1/admin/jobs") == ("admin", 10)
    assert rule_for("GET", "/api/v1/areas") == ("default", 600)
    assert rule_for("GET", "/metrics") is None


def _run_etag(body: bytes, inm: bytes | None = None, status: int = 200):
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "GET", "path": "/api/v1/overview",
             "headers": [(b"if-none-match", inm)] if inm else []}
    asyncio.run(ETagMiddleware(app)(scope, None, send))
    return sent


def test_etag_roundtrip():
    first = _run_etag(b'{"a":1}')
    tag = dict(first[0]["headers"])[b"etag"]
    assert first[0]["status"] == 200 and tag.startswith(b'W/"') and first[1]["body"] == b'{"a":1}'
    again = _run_etag(b'{"a":1}', inm=tag)
    assert again[0]["status"] == 304 and again[1]["body"] == b""
    assert _run_etag(b'{"a":2}', inm=tag)[0]["status"] == 200               # 내용이 바뀌면 새 본문
    assert _run_etag(b"err", status=404)[0]["status"] == 404                # 200 이 아니면 그대로
    assert _matches(b'W/"x", ' + tag, tag) and not _matches(b'W/"x"', tag)
