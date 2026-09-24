"""고도화 ①②④⑤ SQL·API — 소형 지형에서 손 계산 기대값.

지형(conftest): A(0-10k,0-10k) B(10-20k,0-10k) C(0-10k,10-20k) D(10-20k,10-20k), 인구 1000·2000·3000·4000
금융 우체국 F1(5k,2k) F2(15k,9k) F3(5k,16k). 지역 최근접: A 3000 · B 4000 · C 1000 · D 6000 (far = 2000)
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.calc.runner import run_calc
from tests.sql.conftest import X0, Y0

pytestmark = pytest.mark.db
A, B, C, D = "99010", "99020", "99030", "99040"


def add_oa(c, oa_cd, x, y, pop):
    c.execute(text("""
        INSERT INTO mart.oa_area (oa_cd, stat_year, emd_cd, tot_ppltn, geom_5179, rep_point_5179)
        SELECT CAST(:cd AS text), 2024, left(CAST(:cd AS text), 8), :pop, ST_Multi(ST_Buffer(p, 50, 1)), p
          FROM (SELECT ST_SetSRID(ST_MakePoint(:x, :y), 5179) AS p) s"""),
              {"cd": oa_cd, "pop": pop, "x": X0 + x, "y": Y0 + y})


def add_bank(c, pid, x, y, kind="BRANCH"):
    c.execute(text("""
        INSERT INTO mart.bank_place (place_id, name, kind, geom, geom_5179)
        SELECT :id, :nm, :k, ST_Transform(p, 4326), p FROM (SELECT ST_SetSRID(ST_MakePoint(:x, :y), 5179) AS p) s"""),
              {"id": pid, "nm": pid, "k": kind, "x": X0 + x, "y": Y0 + y})


@pytest.fixture()
def extras(terrain, engine):
    with engine.begin() as c:
        add_oa(c, "99010010000001", 5_000, 3_000, 100)    # F1 까지 1,000m
        add_oa(c, "99010010000002", 1_000, 8_000, 300)    # F1 까지 √(4²+6²)=7,211m
        add_bank(c, "BK1", 5_000, 5_500)                   # A 대표점에서 500m
        add_bank(c, "ATM1", 15_000, 15_000, kind="ATM")    # ATM 은 금융 공백 판정에 안 씀
        for hid, m, s in [(terrain["F1"], 4200, 300), (terrain["F2"], 9000, 600)]:
            c.execute(text("""INSERT INTO mart.area_road (adm_cd, stat_year, hist_id, road_m, drive_s, status)
                              VALUES (:a, 2024, :h, :m, :s, 'OK')"""), {"a": A, "h": hid, "m": m, "s": s})
    rid = run_calc(stat_year=2024, levels=[2])
    with engine.connect() as c:
        m = {(a, k): (float(v) if v is not None else None) for a, k, v in c.execute(text(
            "SELECT adm_cd, metric_code, value FROM mart.access_metric WHERE calc_run_id = :r"), {"r": rid})}
    return rid, m


def test_oa_metrics(extras):
    _, m = extras
    assert m[(A, "POPW_FIN_DIST_M")] == pytest.approx((100 * 1000 + 300 * 7211.1) / 400, abs=0.5)
    assert m[(A, "FAR2KM_PPLTN")] == 300 and m[(A, "FAR2KM_SHARE")] == 75.0
    assert (B, "POPW_FIN_DIST_M") not in m          # 집계구 없는 지역은 값 없음


def test_bank_and_fin_gap_metrics(extras):
    _, m = extras
    assert m[(A, "NEAREST_BANK_DIST_M")] == pytest.approx(500, abs=1)
    # A: 은행만 가까움 / B: 둘 다 멂 / C: 우체국만 가까움 / D: 둘 다 멂 (ATM 은 무시)
    assert [m[(x, "POST_ONLY_PPLTN")] for x in (A, B, C, D)] == [0, 0, 3000, 0]
    assert [m[(x, "FIN_DESERT_PPLTN")] for x in (A, B, C, D)] == [0, 2000, 0, 4000]


def test_road_metrics(extras):
    _, m = extras
    assert m[(A, "NEAREST_FIN_ROAD_M")] == 4200 and m[(A, "NEAREST_FIN_DRIVE_MIN")] == 5.0
    assert (B, "NEAREST_FIN_ROAD_M") not in m


@pytest.fixture()
def client(extras):
    from atlas.api.main import app

    with TestClient(app) as c:
        yield c


def test_whatif_fin_loss_and_oa(client, terrain):
    r = client.post("/api/v1/whatif", json={"removeHistIds": [terrain["F3"]], "level": 2}).json()
    # C: 1km → 11.66km, 은행도 9.5km → 금융 창구 상실 3,000명
    assert r["summary"]["lostFinAccessPpltn"] == 3000
    assert {a["admCd"]: a["nearestBankM"] for a in r["areas"]}[C] == pytest.approx(9500, abs=1)   # (5k,15k) ↔ (5k,5.5k)
    r = client.post("/api/v1/whatif", json={"removeHistIds": [terrain["F1"]], "level": 2}).json()
    # 집계구 두 곳 모두 F1 이 1순위 → 영향 400명, 그중 1km 였던 100명이 새로 2km 밖
    assert r["summary"]["oaAffectedPpltn"] == 400 and r["summary"]["oaNewlyFarPpltn"] == 100


@pytest.fixture()
def plain_client(terrain, engine):
    """집계구·은행 없이 지역 대표점만 있는 경우."""
    from atlas.api.main import app

    run_calc(stat_year=2024, levels=[2])
    with TestClient(app) as c:
        yield c


def test_plan_close_area_level(plain_client, terrain):
    r = plain_client.post("/api/v1/plan/close", json={"scope": "99", "k": 1, "weight": "pop", "level": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    # 지역 대표점 기준 단독 영향: F1 = 1000×(10770−3000) / F2 = 2000×6440 + 4000×4050 / F3 = 3000×10662 → F1
    assert body["demandUnit"] == "area"
    assert body["steps"][0]["histId"] == terrain["F1"]
    assert body["steps"][0]["addedKmPpl"] == pytest.approx(7770.3, abs=0.5)
    assert body["weight"] == "pop" and body["candidateCount"] == 3


def test_plan_close_and_open(client, terrain):
    body = client.post("/api/v1/plan/close", json={"scope": "99", "k": 2, "weight": "pop", "level": 2}).json()
    # 집계구 기준: 두 집계구(A 안)는 모두 F1 이 최근접 → F2·F3 는 닫아도 영향 0, F1 이 가장 치명적
    assert body["demandUnit"] == "oa" and body["demandPoints"] == 2
    assert {s["histId"] for s in body["steps"]} == {terrain["F2"], terrain["F3"]}
    assert body["totalAddedKmPpl"] == 0
    crit = body["mostCritical"][0]
    # F1 을 닫으면: 100명 1,000→11,662m(F2) · 300명 7,211→8,944m(F3)
    assert crit["histId"] == terrain["F1"] and crit["newlyFar"] == 100
    assert crit["addedKmPpl"] == pytest.approx((100 * (11661.9 - 1000) + 300 * (8944.3 - 7211.1)) / 1000, abs=1)
    r = client.post("/api/v1/plan/open", json={"scope": "99", "k": 1, "weight": "aged65", "level": 2}).json()
    # KOSIS 없음 → 전체 인구로 대체. D 대표점에 열면 4000명 × 6km = 24,000 명·km, 4000명이 2km 안으로
    assert r["weightFallback"] is True
    assert r["steps"][0]["siteCd"] == D and r["steps"][0]["gainKmPpl"] == 24000 and r["steps"][0]["newlyNear"] == 4000
    assert client.post("/api/v1/plan/close", json={"scope": "9", "k": 1}).status_code == 400
    assert client.post("/api/v1/plan/close", json={"scope": "99", "k": 8}).status_code == 400
    assert client.post("/api/v1/plan/close", json={"scope": "11", "k": 1}).status_code == 404


def test_banks_layer_and_detail(client):
    b = client.get("/api/v1/banks", params={"bbox": "120,30,135,40"}).json()
    assert [x["placeId"] for x in b["items"]] == ["BK1"]
    assert len(client.get("/api/v1/banks", params={"bbox": "120,30,135,40", "atm": True}).json()["items"]) == 2
    d = client.get(f"/api/v1/areas/{A}").json()
    assert d["nearestBanks"][0]["name"] == "BK1"
    assert d["nearest"][0]["roadM"] == 4200 and d["nearest"][0]["driveMin"] == 5.0


def test_road_repair_targets(extras, engine, terrain):
    """보정 대상: 대표점 출발 실패(NO_ROUTE) · 직선의 4배 넘는 우회. 출발점은 인구가 가장 많은 집계구."""
    from atlas.collector.kakao.road import DETOUR_RATIO, _REPAIR

    with engine.begin() as c:
        c.execute(text("""INSERT INTO mart.area_road (adm_cd, stat_year, hist_id, status, detail)
                          VALUES (:a, 2024, :h, 'NO_ROUTE', '102 시작 지점 주변 도로 없음')"""), {"a": A, "h": terrain["F3"]})
        c.execute(text("UPDATE mart.area_road SET road_m = 50000 WHERE adm_cd = :a AND hist_id = :h"),
                  {"a": A, "h": terrain["F1"]})           # 직선 3,000m 의 16배
        rows = c.execute(_REPAIR, {"y": 2024, "ratio": DETOUR_RATIO, "lim": 100}).all()
    assert {r[3] for r in rows} == {terrain["F1"], terrain["F3"]}      # F2(9,000 / 직선 10,770)는 정상
    ox, oy = rows[0][1], rows[0][2]
    with engine.connect() as c:   # 출발점 = 인구 300명 집계구 (1k, 8k)
        x, y = c.execute(text("SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 5179) p) s"),
                         {"x": ox, "y": oy}).one()
    assert abs(x - (X0 + 1000)) < 1 and abs(y - (Y0 + 8000)) < 1
