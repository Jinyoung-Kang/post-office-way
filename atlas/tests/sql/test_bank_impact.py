"""① 은행 지점 폐쇄 영향평가(calc/11_bank_impact.sql) — 소형 지형에서 손 계산.

금융 우체국 F1(5k,2k) F2(15k,9k) F3(5k,16k). 집계구 OA1(5k,3k) 100명 · OA2(1k,8k) 300명 · OA3(2k,7.5k) 50명 (모두 지역 A).
은행: K1 KB국민(2k,7k) · S1 신한(18k,18k) · 새마을금고 M1(1k,8.1k, 평가·대체 대상 아님).
K1 이 닫히면 — OA1: 지금도 K1 이 5km(2km 밖)라 '새로 잃는' 주민 아님 / OA2: 지금 1,414m → 대체 F1 7,211m(잃음 300) /
OA3: 지금 500m → 대체 F1 6,265m(잃음 50).
"""
import math

import pytest
from sqlalchemy import text

from atlas.calc.runner import run_calc
from tests.sql.conftest import X0, Y0
from tests.sql.test_extras import add_oa

pytestmark = pytest.mark.db


def add_branch(c, pid, x, y, brand, category=None):
    c.execute(text("""
        INSERT INTO mart.bank_place (place_id, name, category, brand, kind, geom, geom_5179)
        SELECT :id, :nm, :cat, :b, 'BRANCH', ST_Transform(p, 4326), p
          FROM (SELECT ST_SetSRID(ST_MakePoint(:x, :y), 5179) AS p) s"""),
              {"id": pid, "nm": pid, "b": brand, "cat": category or f"금융,보험 > 금융서비스 > 은행 > {brand}", "x": X0 + x, "y": Y0 + y})


@pytest.fixture()
def impact(terrain, engine):
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
        add_oa(c, "99010010000002", 1_000, 8_000, 300)
        add_oa(c, "99010010000003", 2_000, 7_500, 50)
        add_branch(c, "K1", 2_000, 7_000, "KB국민은행")
        add_branch(c, "S1", 18_000, 18_000, "신한은행")
        add_branch(c, "M1", 1_000, 8_100, "새마을금고")
        # 집계구 읍면동(앞 8자리)의 고령 비율 30% → OA1 30명 · OA2 90명 · OA3 15명
        c.execute(text("""INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn,
                              aged65_ratio, match_method) VALUES ('99010010', 2024, '202412', 400, 120, 30, 'NAME')"""))
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        rows = {r.place_id: r for r in c.execute(text("SELECT * FROM mart.bank_impact WHERE calc_run_id = :r"), {"r": rid})}
    return rid, rows


def test_catchment_alternatives_and_lost_population(impact):
    _, b = impact
    assert set(b) == {"K1", "S1"}                       # 새마을금고는 평가 대상 아님
    k1 = b["K1"]
    assert (k1.catch_oa, k1.catch_ppltn, k1.lost_ppltn) == (3, 450, 350)
    assert k1.catch_aged == 135 and k1.lost_aged == 105
    now = (100 * 5_000 + 300 * math.hypot(1_000, 1_000) + 50 * 500) / 450
    alt = (100 * 1_000 + 300 * math.hypot(4_000, 6_000) + 50 * math.hypot(3_000, 5_500)) / 450   # 모두 F1(은행대리업)
    assert float(k1.popw_now_m) == pytest.approx(now, abs=1) and float(k1.popw_alt_m) == pytest.approx(alt, abs=1)
    assert k1.same_brand_m is None and float(k1.other_bank_m) == pytest.approx(math.hypot(16_000, 11_000), abs=1)
    assert float(k1.post_m) == pytest.approx(math.hypot(3_000, 5_000), abs=1) and k1.post_agent
    assert k1.adm_cd == "99010"


def test_grade_rule(impact):
    _, b = impact
    # K1: 새로 잃는 주민 350 + 같은 은행 10km 안 지점 없음 + 고령 30% → HIGH
    assert b["K1"].grade == "HIGH" and set(b["K1"].reasons) == {"NO_ALT_2KM", "SAME_BANK_10KM", "AGED_20"}
    # S1: 이용 주민 없음, 같은 은행 다른 지점 없음 → MID
    assert b["S1"].grade == "MID" and b["S1"].reasons == ["SAME_BANK_10KM"]
    assert (b["K1"].rnk, b["S1"].rnk, b["K1"].n) == (1, 2, 2)


def test_grade_function_thresholds(engine):
    with engine.connect() as c:
        g = lambda lost, rs: c.execute(text("SELECT mart.bank_impact_grade(:l, CAST(:r AS text[]))"),  # noqa: E731
                                       {"l": lost, "r": rs}).scalar()
        assert g(1000, ["NO_ALT_2KM"]) == "HIGH"            # 대체 없는 주민 1,000명 이상
        assert g(10, ["NO_ALT_2KM"]) == "MID"
        assert g(10, ["NO_ALT_2KM", "AGED_20"]) == "HIGH"
        assert g(0, []) == "LOW"


def test_oa_bank_rows(impact, engine):
    rid, _ = impact
    with engine.connect() as c:
        rows = {r.oa_cd: r for r in c.execute(text("SELECT * FROM mart.oa_bank WHERE calc_run_id = :r"), {"r": rid})}
    assert rows["99010010000001"].b1 == "K1" and rows["99010010000001"].alt_m == pytest.approx(1_000, abs=1)
    assert rows["99010010000001"].d1 == pytest.approx(5_000, abs=1)
    assert rows["99010010000002"].alt_m == pytest.approx(math.hypot(4_000, 6_000), abs=1) and rows["99010010000002"].aged == 90


@pytest.fixture()
def client(impact):
    from fastapi.testclient import TestClient

    from atlas.api.main import app

    with TestClient(app) as c:
        yield c


def test_impact_api_list_detail_geojson(client):
    r = client.get("/api/v1/banks/impact").json()
    assert r["summary"] == {"branches": 2, "high": 1, "mid": 1, "low": 0, "lostPpltn": 350, "walkLostPpltn": 0,
                            "catchPpltn": 450}
    assert [i["placeId"] for i in r["items"]] == ["K1", "S1"] and r["items"][0]["reasons"]
    assert client.get("/api/v1/banks/impact", params={"grade": "MID"}).json()["total"] == 1
    assert client.get("/api/v1/banks/impact", params={"sgg": "99020"}).json()["total"] == 0
    d = client.get("/api/v1/banks/impact/K1").json()
    kinds = {a["kind"] for a in d["alternatives"]}
    assert kinds == {"OTHER_BANK", "POST"}                       # 같은 은행 다른 지점은 없음
    # 닫히면 대체 창구까지: OA1 1,000m(1~2km 칸) · OA2 7,211m · OA3 6,265m(5~10km 칸)
    assert [b["ppltn"] for b in d["altBands"]] == [0, 100, 0, 350, 0]
    g = client.get("/api/v1/banks/impact/K1/geojson").json()
    assert len(g["features"]) == 3 and {f["properties"]["admCd"] for f in g["features"]} >= {"99010010000002"}


def test_impact_api_errors(client):
    assert client.get("/api/v1/banks/impact/M1").json()["code"] == "BANK_IMPACT_NOT_FOUND"   # 새마을금고
    assert client.get("/api/v1/banks/impact/a%27b").status_code in (400, 404, 422)
    for bad in ({"sort": "x"}, {"grade": "BAD"}, {"sido": "1"}, {"page": 0}, {"size": 101}):
        assert client.get("/api/v1/banks/impact", params=bad).status_code == 400, bad


def test_region_report(client):
    r = client.get("/api/v1/areas/99010/report").json()
    assert r["area"]["admCd"] == "99010" and r["banks"]["branches"] == 1 and r["banks"]["top"][0]["placeId"] == "K1"
    codes = {m["code"] for m in r["metrics"]}
    assert {"POPW_FIN_DIST_M", "FAR2KM_SHARE"} <= codes and all(m["median"] is not None for m in r["metrics"])
    assert [p["name"] for p in r["posts"]] == ["F1"]
    assert client.get("/api/v1/areas/99/report").status_code == 400
    assert client.get("/api/v1/areas/12345/report").json()["code"] == "AREA_NOT_FOUND"


def test_branch_just_outside_boundary_gets_nearest_area(terrain, engine):
    """해안선 단순화 등으로 경계 밖에 조금 떨어진 지점도 우체국과 같은 규칙(snapM 2km 안 최근접 지역)으로 지역이 정해져야 함.
    예전에는 지점만 '폴리곤 안'만 봐서 지역이 비어(실데이터: 경계 밖 16m 의 HIGH 지점) 시군구 보고서·시도 필터에서 빠졌음."""
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)
        add_branch(c, "K9", -16, 5_000, "KB국민은행")            # 지역 A 왼쪽 경계에서 16m 밖
        add_branch(c, "K8", -3_000, 5_000, "신한은행")           # 2km 넘게 밖 — 지금처럼 지역 없음
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        got = dict(c.execute(text("SELECT place_id, adm_cd FROM mart.bank_impact WHERE calc_run_id = :r"), {"r": rid}).all())
    assert got == {"K9": "99010", "K8": None}
