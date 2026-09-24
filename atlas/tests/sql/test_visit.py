"""⑥ 방문 여건 — 수집(가짜 응답) → 적재(더 최근 발표만 덮어씀) → 조회 API 판정·영향 고령인구."""
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.calc.runner import run_calc
from atlas.collector.weather import air, kma
from tests.sql.conftest import add_area, add_pop

pytestmark = pytest.mark.db
FIX = Path(__file__).resolve().parents[1] / "contract" / "fixtures"
UISEONG = "37520"


class FakeFetcher:
    calls = errors = 0

    def close(self):
        pass


def _kma_body(nx, ny):
    """모든 격자에 같은 예보(24일 맑음 · 25일 호우) — 격자 좌표만 바꿈."""
    body = json.loads((FIX / "kma_vilage_sample.json").read_text())["response"]["body"]
    for it in body["items"]["item"]:
        it["nx"], it["ny"] = nx, ny
    return body


@pytest.fixture()
def weather(terrain, engine, monkeypatch):
    with engine.begin() as c:
        add_area(c, UISEONG, 30_000, 0, 40_000, 10_000, parent="37", nm="의성군")   # 경북 권역 대기 예보 확인용
        add_pop(c, UISEONG, 5000, 900)
    run_calc(stat_year=2024, levels=[2])
    calls = []

    def fake_kma(fetcher, url, params, source):
        calls.append((params["nx"], params["ny"], params["base_time"]))
        return _kma_body(params["nx"], params["ny"])

    air_body = json.loads((FIX / "air_frcst_pm10_sample.json").read_text())["response"]["body"]
    monkeypatch.setattr(kma, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(kma, "call", fake_kma)
    monkeypatch.setattr(air, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(air, "call", lambda f, u, p, s: air_body if p["InformCode"] == "PM10" else {})
    rid_kma = kma.collect_kma(now=datetime(2026, 9, 24, 5, 30))
    rid_air = air.collect_air(now=datetime(2026, 9, 24, 12, 0))
    return {"kma": rid_kma, "air": rid_air, "calls": calls}


def test_collect_loads_grids_hours_and_air(weather, engine):
    with engine.connect() as c:
        grids = c.execute(text("SELECT count(*), count(DISTINCT (nx, ny)) FROM mart.area_grid")).one()
        hours = c.execute(text("SELECT count(*), min(base_at) FROM mart.weather_hourly")).one()
        runs = dict(c.execute(text("SELECT kind, status FROM ops.collect_run WHERE kind IN ('KMA_FCST', 'AIR_FCST')")).all())
        airn = c.execute(text("SELECT count(*) FROM mart.air_forecast WHERE inform_code = 'PM10'")).scalar()
    assert grids[0] == 5 and len(weather["calls"]) == grids[1]           # 격자 중복 없이 한 번씩
    assert {b for *_, b in weather["calls"]} == {"0500"}
    assert hours[0] == grids[1] * 42 and hours[1] == datetime(2026, 9, 24, 5)
    assert runs == {"KMA_FCST": "DONE", "AIR_FCST": "DONE"} and airn == 19 * 2


def test_older_forecast_does_not_overwrite(weather, engine):
    with engine.begin() as c:
        c.execute(text("UPDATE mart.weather_hourly SET base_at = '2026-09-24 08:00', tmp = 99"))
    kma.collect_kma(now=datetime(2026, 9, 24, 5, 30))                         # 05시 발표를 다시 받아도
    with engine.connect() as c:
        assert c.execute(text("SELECT min(tmp), max(tmp) FROM mart.weather_hourly")).one() == (99, 99)


@pytest.fixture()
def client(weather):
    from atlas.api.main import app

    with TestClient(app) as c:
        yield c


def test_conditions_api(client):
    good = client.get("/api/v1/visit/conditions", params={"date": "2026-09-24"}).json()
    assert good["meta"]["ruleVersion"] == "VISIT-1" and good["summary"]["byLevel"]["좋음"] == 5
    u = next(x for x in good["items"] if x["admCd"] == UISEONG)
    assert u["airRegion"] == "경북" and u["pm10"] == "보통" and u["level"] == 0 and u["atRiskAged"] == 0

    bad = client.get("/api/v1/visit/conditions", params={"date": "2026-09-25"}).json()
    assert bad["summary"]["byLevel"]["나쁨"] == 5 and bad["summary"]["byReason"]["RAIN"] == 5
    u = next(x for x in bad["items"] if x["admCd"] == UISEONG)
    assert [r["code"] for r in u["reasons"]] == ["RAIN", "WIND", "PM10"]      # 호우 · 바람 9.5m/s · 경북 미세먼지 나쁨
    assert u["pcpMm"] == 36.5 and u["tmpMax"] == 18
    # 먼 곳 고령인구 순 — 영향 합계는 여건 나쁜 지역의 AGED65_FAR_PPLTN 합
    assert bad["summary"]["atRiskAged"] == sum(x["agedFarPpltn"] or 0 for x in bad["items"])
    assert client.get("/api/v1/visit/conditions", params={"date": "2026-09-25", "sido": "37"}).json()["summary"]["areas"] == 1


def test_area_outlook_and_errors(client):
    r = client.get(f"/api/v1/visit/conditions/{UISEONG}00100")                  # 읍면동 코드 → 상위 시군구
    assert r.status_code == 200 and r.json()["admCd"] == UISEONG
    assert client.get("/api/v1/visit/conditions/abc").status_code == 400
    assert client.get("/api/v1/visit/conditions", params={"date": "20260925"}).status_code == 400
    assert client.get("/api/v1/visit/conditions", params={"date": "2020-01-01"}).json()["code"] == "VISIT_NO_DATA"
