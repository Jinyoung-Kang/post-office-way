"""수집 데이터 보호 장치 — 이상한 응답(빈 응답·건수 누락·일부 실패)이 기존 자료를 지우지 않는지 (ADR-023)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from atlas.collector.datago import care

pytestmark = pytest.mark.db


class FakeFetcher:
    calls = errors = 0

    def close(self):
        pass


def _seed_pharmacies(engine, n: int) -> None:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO mart.care_place (hpid, kind, name, hours, geom, geom_5179, last_seen)
            SELECT 'OLD' || i, 'PHARMACY', '약국' || i, '{}'::jsonb, p, ST_Transform(p, 5179), now() - interval '7 days'
              FROM generate_series(1, :n) i, (SELECT ST_SetSRID(ST_MakePoint(127.0, 37.0), 4326) AS p) s"""), {"n": n})


def _pharmacies(engine) -> int:
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM mart.care_place WHERE kind = 'PHARMACY'")).scalar_one()


def _item(i: int) -> dict:
    return {"hpid": f"NEW{i}", "dutyName": f"약국{i}", "wgs84Lat": 37.0, "wgs84Lon": 127.0}


def _run_care(monkeypatch, pharmacy_body, clinic_body=None) -> tuple[str, dict]:
    clinic_body = clinic_body if clinic_body is not None else {
        "items": {"item": [{"hpid": "C1", "dutyName": "의원1", "dutyDiv": "C", "dutyDivNam": "의원",
                            "wgs84Lat": 37.0, "wgs84Lon": 127.0}]}, "totalCount": 1}
    monkeypatch.setattr(care, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(care, "call", lambda f, url, p, src: pharmacy_body if src == "NMC_PHARMACY" else clinic_body)
    rid = care.collect_care()
    from atlas.core.db import begin

    with begin() as c:
        return tuple(c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"),
                               {"r": rid}).one())


@pytest.mark.parametrize("body", [
    {},                                                             # 결과 없음(03) → call 이 빈 dict
    {"items": {"item": [_item(1)]}},                                # 전체 건수(totalCount) 없음
    {"items": "", "totalCount": 25000},                             # 건수는 있는데 항목이 빔
])
def test_care_anomalous_response_keeps_existing(clean, engine, monkeypatch, body):
    _seed_pharmacies(engine, 200)
    status, stats = _run_care(monkeypatch, body)
    assert _pharmacies(engine) >= 200                               # 기존 약국을 지우지 않음
    assert status != "DONE" and not stats["pharmacy"]["complete"]


def test_care_mass_removal_is_held(clean, engine, monkeypatch):
    """전체를 받았다고 해도 기존 행의 큰 비율이 한 번에 사라지면 삭제를 보류 (응답 이상으로 봄)."""
    _seed_pharmacies(engine, 200)
    status, stats = _run_care(monkeypatch, {"items": {"item": [_item(i) for i in range(20)]}, "totalCount": 20})
    assert _pharmacies(engine) == 220 and stats["pharmacy"]["removeHeld"] == 200 and status != "DONE"


def test_care_normal_closure_removes_unseen(clean, engine, monkeypatch):
    """정상 — 전체를 받았고 사라진 곳이 적으면 폐업한 곳만 지움."""
    _seed_pharmacies(engine, 2)
    items = [_item(i) for i in range(100)]
    status, stats = _run_care(monkeypatch, {"items": {"item": items}, "totalCount": 100})
    assert _pharmacies(engine) == 100 and stats["pharmacy"]["removed"] == 2 and status == "DONE"
