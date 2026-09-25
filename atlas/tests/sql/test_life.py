"""⑦ 생활 거점 — 약국·의원 적재(가짜 응답) → 계산(09_life.sql) → 지표·우체국별 대체 불가능성 → What-if·API.

지형(conftest): A(0-10k,0-10k) … 금융 우체국 F1(5k,2k) F2(15k,9k) F3(5k,16k). 은행 BK1(5k,5.5k).
A 안 집계구: OA1(5k,3k) 100명 · OA2(1k,8k) 300명 · OA3(5k,1k) 50명. 약국 P1(5k,3.5k) · 의원 C1(1k,8.5k, 공휴일 진료)
  OA1: F1 1,000m · 약국 500m          → 생활 거점 있음, 공휴일 진료처 6.8km → 공휴일 의료 공백
  OA2: F1 7,211m · 의원 500m          → 2km 밖이지만 의료 거점 있음
  OA3: F1 1,000m · 은행 4.5km·약국 2.5km·의원 먼 곳 → 우체국이 마지막 생활 거점 (50명)
"""
import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.calc.runner import run_calc
from atlas.collector.datago import care, holiday
from tests.sql.conftest import X0, Y0

pytestmark = pytest.mark.db
A = "99010"


def add_oa(c, oa_cd, x, y, pop):
    c.execute(text("""INSERT INTO mart.oa_area (oa_cd, stat_year, emd_cd, tot_ppltn, geom_5179, rep_point_5179)
                      SELECT CAST(:cd AS text), 2024, left(CAST(:cd AS text), 8), :pop, ST_Multi(ST_Buffer(p, 50, 1)), p
                        FROM (SELECT ST_SetSRID(ST_MakePoint(:x, :y), 5179) AS p) s"""),
              {"cd": oa_cd, "pop": pop, "x": X0 + x, "y": Y0 + y})


def lonlat(c, x, y):
    return c.execute(text("SELECT ST_X(g), ST_Y(g) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 5179), 4326) g) s"),
                     {"x": X0 + x, "y": Y0 + y}).one()


class FakeFetcher:
    calls = errors = 0

    def close(self):
        pass


@pytest.fixture()
def life(terrain, engine, monkeypatch):
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
        add_oa(c, "99010010000002", 1_000, 8_000, 300)
        add_oa(c, "99010010000003", 5_000, 1_000, 50)
        c.execute(text("""INSERT INTO mart.bank_place (place_id, name, kind, geom, geom_5179)
                          SELECT 'BK1', '은행', 'BRANCH', ST_Transform(p, 4326), p
                            FROM (SELECT ST_SetSRID(ST_MakePoint(:x, :y), 5179) AS p) s"""), {"x": X0 + 5_000, "y": Y0 + 5_500})
        p_lon, p_lat = lonlat(c, 5_000, 3_500)
        c_lon, c_lat = lonlat(c, 1_000, 8_500)
    pages = {
        "NMC_PHARMACY": {"items": {"item": [{"hpid": "P1", "dutyName": "약국1", "wgs84Lat": p_lat, "wgs84Lon": p_lon,
                                              "dutyTime1s": "0900", "dutyTime1c": 1800}]}, "totalCount": 1},
        "NMC_HOSPITAL": {"items": {"item": [{"hpid": "C1", "dutyName": "의원1", "dutyDiv": "C", "dutyDivNam": "의원",
                                              "wgs84Lat": c_lat, "wgs84Lon": c_lon, "dutyTime8s": "0900", "dutyTime8c": "1300"},
                                             {"hpid": "E1", "dutyName": "한방", "dutyDiv": "E", "wgs84Lat": c_lat,
                                              "wgs84Lon": c_lon}]}, "totalCount": 2},
    }
    monkeypatch.setattr(care, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(care, "call", lambda f, url, p, src: pages[src])
    rid = care.collect_care()
    calc = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        m = {(a, k): (float(v) if v is not None else None) for a, k, v in c.execute(text(
            "SELECT adm_cd, metric_code, value FROM mart.access_metric WHERE calc_run_id = :r"), {"r": calc})}
    return {"collect": rid, "calc": calc, "m": m}


def test_care_collect(life, engine):
    with engine.connect() as c:
        rows = c.execute(text("SELECT hpid, kind, open_holiday FROM mart.care_place ORDER BY hpid")).all()
        st = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": life["collect"]}).one()
    assert rows == [("C1", "CLINIC", True), ("P1", "PHARMACY", False)]           # 한방병원 제외
    assert st[0] == "DONE" and st[1]["clinic"]["skipped"] == 1 and st[1]["pharmacy"]["complete"]


def test_life_metrics(life):
    m = life["m"]
    assert m[(A, "CARE_DESERT_PPLTN")] == 50
    assert m[(A, "POST_SOLE_HUB_PPLTN")] == 50
    assert m[(A, "LIFE_DESERT_PPLTN")] == 0
    assert m[(A, "HOLIDAY_CARE_GAP_PPLTN")] == 150
    assert m[(A, "POPW_PHARMACY_DIST_M")] == pytest.approx((100 * 500 + 300 * 6020.8 + 50 * 2500) / 450, abs=1)


def test_facility_hub(life, engine, terrain):
    with engine.connect() as c:
        r = c.execute(text("""SELECT served_ppltn, sole_fin_ppltn, sole_hub_ppltn, oa_count FROM mart.facility_hub
                              WHERE calc_run_id = :r AND hist_id = :h"""), {"r": life["calc"], "h": terrain["F1"]}).one()
    assert tuple(r) == (150, 150, 50, 2)


@pytest.fixture()
def client(life):
    from atlas.api.main import app

    with TestClient(app) as c:
        yield c


def test_whatif_life_hub_lost(client, terrain):
    s = client.post("/api/v1/whatif", json={"removeHistIds": [terrain["F1"]], "level": 2}).json()["summary"]
    assert s["oaNewlyFarPpltn"] == 150 and s["lifeHubLostPpltn"] == 50     # OA1 은 약국이 남음


def test_hub_endpoints(client, terrain):
    sm = client.get("/api/v1/hubs/summary").json()
    assert sm["available"] and sm["totals"]["soleHubPpltn"] == 50 and sm["care"]["clinic"] == 1
    assert sm["facilities"]["withSoleHub"] == 1 and sm["topAreas"][0]["admCd"] == A
    fs = client.get("/api/v1/hubs/facilities").json()
    assert fs["items"][0]["histId"] == terrain["F1"] and fs["items"][0]["soleHubPpltn"] == 50
    assert client.get("/api/v1/hubs/facilities", params={"sort": "bogus"}).status_code == 400
    det = client.get(f"/api/v1/facilities/{terrain['F1']}").json()
    assert det["hub"]["soleHubPpltn"] == 50 and det["hub"]["soleHubRank"] == 1
    assert {n["kind"] for n in det["hub"]["nearby"]} == {"PHARMACY", "CLINIC", "BANK"}
    assert det["status"]["state"] in ("open", "before", "after", "closed", "unknown")
    lo, la = det["lon"], det["lat"]
    layer = client.get("/api/v1/care", params={"bbox": f"{lo - .2},{la - .2},{lo + .2},{la + .2}", "holidayOnly": True}).json()
    assert [x["id"] for x in layer["items"]] == ["C1"]
    assert client.get("/api/v1/care", params={"bbox": "120,30,135,40"}).status_code == 400     # 너무 넓음
    ov = client.get("/api/v1/overview").json()
    assert ov["life"]["soleHubPpltn"] == 50 and ov["topSoleHub"][0]["admCd"] == A


def test_holidays_and_calendar(engine, monkeypatch, clean):
    body = json.loads(open("tests/contract/fixtures/kasi_holiday_sample.json").read())["response"]["body"]
    monkeypatch.setattr(holiday, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(holiday, "call", lambda f, u, p, s: body if p["solYear"] == 2026 else {})
    holiday.collect_holidays(years=[2026, 2027])
    holiday.collect_holidays(years=[2026])                                      # 다시 받아도 중복 없이 교체
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM mart.holiday")).scalar() == 6
    from atlas.api.main import app

    with TestClient(app) as cl:
        cal = cl.get("/api/v1/calendar", params={"start": "2026-09-24", "days": 5}).json()
    assert cal["hasCalendar"] and [d["closed"] for d in cal["items"]] == [True, True, True, True, False]
    assert cal["items"][1]["reason"] == "추석" and cal["items"][1]["runDays"] == 4
    assert cal["items"][4]["runDays"] is None


def test_business_day_flags_in_visit(engine, monkeypatch, terrain):
    """방문 여건 날짜에 창구 휴무(공휴일·주말) 표시."""
    with engine.begin() as c:
        c.execute(text("INSERT INTO mart.holiday (locdate, name, is_holiday) VALUES ('2026-09-25', '추석', true)"))
        c.execute(text("INSERT INTO mart.area_grid (adm_cd, stat_year, nx, ny) VALUES ('99010', 2024, 1, 1)"))
        c.execute(text("""INSERT INTO mart.weather_hourly (nx, ny, fcst_at, base_at, tmp, pty, wsd)
                          SELECT 1, 1, t, '2026-09-25 05:00', 20, 0, 2
                            FROM generate_series(timestamp '2026-09-25 00:00', timestamp '2026-09-26 23:00', interval '1 hour') t"""))
    from atlas.api.main import app

    with TestClient(app) as cl:
        v = cl.get("/api/v1/visit/conditions", params={"date": "2026-09-25"}).json()
        v2 = cl.get("/api/v1/visit/conditions", params={"date": "2026-09-26"}).json()
    assert v["meta"]["closed"] and v["meta"]["closedReason"] == "추석" and v["meta"]["hasCalendar"]
    assert v2["meta"]["closedReason"] == "토요일"
    assert "has365" in v["items"][0] and "holidayCareGapPpltn" in v["summary"]
    _ = (date, datetime)


def test_geojson_gzip_etag_and_ranks(client):
    url = "/api/v1/areas/geojson?level=2&metric=POST_SOLE_HUB_PPLTN"
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and r.headers["etag"].startswith('W/"')
    a = next(f for f in r.json()["features"] if f["properties"]["admCd"] == A)
    assert a["properties"]["rank"] == 1 and a["properties"]["rankOf"] == 1        # 계산 때 넣은 순위(V14) — 집계구가 있는 A 만 값
    assert client.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    plain = client.get(url, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json()["meta"]["metric"] == "POST_SOLE_HUB_PPLTN"
    det = client.get(f"/api/v1/areas/{A}").json()
    m = next(x for x in det["metrics"] if x["code"] == "POST_SOLE_HUB_PPLTN")
    assert m["rank"] == 1 and m["rankOf"] == 1
