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


def test_available_dates_window(clean, engine):
    """예보가 창구 시간(09~18시)에 있는 날만, 오늘부터 4일 — 창구 시간 밖 예보만 있는 날·지난 날은 빠짐."""
    from datetime import date

    from atlas.features.visit import available_dates

    rows = [("2026-10-08 12:00", 1),                      # 어제 — 빠짐
            ("2026-10-09 08:00", 2), ("2026-10-09 18:00", 3),   # 오늘: 18시대는 창구 시간(18:59 까지)
            ("2026-10-10 06:00", 4), ("2026-10-10 21:00", 5),   # 창구 시간 밖만 — 빠짐
            ("2026-10-11 09:00", 6), ("2026-10-12 13:00", 7), ("2026-10-13 10:00", 8), ("2026-10-14 10:00", 9)]
    with clean.begin() as c:
        for at, n in rows:
            c.execute(text("INSERT INTO mart.weather_hourly (nx, ny, fcst_at, base_at) VALUES (60, :n, CAST(:at AS timestamp), now())"),
                      {"n": n, "at": at})
        got = available_dates(c, date(2026, 10, 9))
    assert got == [date(2026, 10, 9), date(2026, 10, 11), date(2026, 10, 12), date(2026, 10, 13)]


def _kma_with(monkeypatch, fetch, grids=20):
    from atlas.core.config import get_settings

    monkeypatch.setattr(get_settings(), "datago_concurrency", 4)
    monkeypatch.setattr(kma, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(kma, "ensure_grids", lambda c, y: [(i, 1) for i in range(grids)])
    monkeypatch.setattr(kma, "fetch_grid", lambda f, base, nx, ny: fetch(nx))


def test_kma_stop_keeps_fetched_grids(clean, engine, monkeypatch):
    """호출 한도(DataGoStop)로 멈춰도 그때까지 받은 격자 예보는 모두 저장 — 예전에는 끝난 결과를 임의 순서로 돌다 중단을
    만나면 나머지를 버려, 한도를 쓴 예보 대부분이 사라졌음(datago/client 의 '이미 받은 결과는 남음'과 다름)."""
    import time as _t

    from atlas.collector.datago.client import DataGoStop

    def fetch(nx):
        if nx == 0:
            _t.sleep(0.2)
            raise DataGoStop("22 일일 호출 한도")
        return {datetime(2026, 9, 24, 6): {"tmp": 20}}

    _kma_with(monkeypatch, fetch)
    for _ in range(3):                                   # 예전 결과는 집합 순서에 따라 달라 여러 번 확인
        rid = kma.collect_kma(now=datetime(2026, 9, 24, 5, 30))
        with engine.connect() as c:
            st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
        assert stats["done"] == 19 and stats["stoppedBy"] and st == "PARTIAL"


def test_kma_unexpected_error_cancels_remaining_calls(clean, engine, monkeypatch):
    """예상 밖 오류면 남은 격자를 부르지 않고 끝냄 — 예전에는 남은 호출을 모두 한 뒤 결과를 버리고 FAILED 였음."""
    import time as _t

    calls = []

    def fetch(nx):
        calls.append(nx)
        if nx == 0:
            raise ValueError("해석할 수 없는 응답")
        _t.sleep(0.05)
        return {datetime(2026, 9, 24, 6): {"tmp": 20}}

    _kma_with(monkeypatch, fetch, grids=40)
    with pytest.raises(ValueError):
        kma.collect_kma(now=datetime(2026, 9, 24, 5, 30))
    assert len(calls) < 40


def test_conditions_cache_follows_grid_commits(weather, engine, monkeypatch):
    """기상청 수집은 격자마다 커밋함 — 첫 격자가 커밋된 순간의 섞인 판정이 수집이 끝난 뒤에도 30분 캐시되면 안 됨.
    예전 캐시 버전은 '그날 예보의 최신 발표 시각'뿐이라 첫 격자 뒤로 바뀌지 않았음."""
    from atlas.core import cache
    from atlas.features import visit

    store: dict[str, bytes] = {}
    monkeypatch.setattr(cache, "get", lambda k: store.get(k))
    monkeypatch.setattr(cache, "set", lambda k, v, ttl=None: store.__setitem__(k, v.encode() if isinstance(v, str) else v))
    with engine.connect() as c:
        grids = c.execute(text("SELECT DISTINCT nx, ny FROM mart.weather_hourly ORDER BY 1, 2")).all()
    assert len(grids) > 1
    clear = """UPDATE mart.weather_hourly SET base_at = '2026-09-24 08:00', pty = 0, pop = 0, pcp_mm = 0, sno_cm = 0, wsd = 1
                WHERE (nx, ny) {} (:nx, :ny)"""
    with engine.begin() as c:                                    # 새 발표(08시)가 첫 격자에만 들어간 순간
        c.execute(text(clear.format("=")), {"nx": grids[0][0], "ny": grids[0][1]})
    with engine.connect() as c:
        visit.conditions_json(c, "2026-09-25")
    with engine.begin() as c:                                    # 나머지 격자도 들어옴 — 수집 끝
        c.execute(text(clear.format("<>")), {"nx": grids[0][0], "ny": grids[0][1]})
    with engine.connect() as c:
        done = json.loads(visit.conditions_json(c, "2026-09-25"))
    assert "RAIN" not in done["summary"]["byReason"]


def test_kma_stop_cancels_queued_and_keeps_in_flight(clean, engine, monkeypatch):
    """중단이 일찍 오면 아직 시작하지 않은 격자는 부르지 않고, 그때 돌고 있던 격자의 결과는 저장 — 취소 경로(독립 검토의 테스트 공백)."""
    import threading
    import time as _t

    from atlas.collector.datago.client import DataGoStop

    calls, lock = [], threading.Lock()

    def fetch(nx):
        with lock:
            calls.append(nx)
        if nx == 0:
            raise DataGoStop("22 일일 호출 한도")
        _t.sleep(0.05)
        return {datetime(2026, 9, 24, 6): {"tmp": 20}}

    _kma_with(monkeypatch, fetch, grids=40)
    rid = kma.collect_kma(now=datetime(2026, 9, 24, 5, 30))
    with engine.connect() as c:
        st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
    assert len(calls) < 40 and stats["stoppedBy"] and st == "PARTIAL"
    assert stats["done"] == len(calls) - 1                  # 부른 격자 가운데 중단 하나를 뺀 나머지는 모두 저장
