"""HTTP 계층 회귀 테스트 — 소형 지형 + calc 1회 후 FastAPI TestClient 로 호출.
검토에서 찾은 버그(와일드카드 검색, 없는 리소스 200, 잘못된 파라미터 통과, calc 종료 시각)를 고정합니다."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.calc.runner import run_calc

pytestmark = pytest.mark.db
NIL = "00000000-0000-0000-0000-000000000000"


@pytest.fixture()
def client(terrain, engine):
    from atlas.api.main import app

    rid = run_calc(stat_year=2024, levels=[2])
    with TestClient(app) as c:
        c.rid = str(rid)
        yield c


def test_core_endpoints(client, terrain):
    assert client.get("/api/v1/health").json()["db"] is True
    fc = client.get("/api/v1/areas/geojson", params={"level": 2, "metric": "NEAREST_FIN_DIST_M"}).json()
    assert fc["meta"]["calcRunId"] == client.rid and len(fc["features"]) == 4
    d = client.get("/api/v1/areas/99040").json()
    assert d["nearest"][0]["histId"] == terrain["F2"] and d["residentPop"] is None
    ov = client.get("/api/v1/overview").json()
    assert ov["finTotal"] == 3 and ov["kosis"] is None
    m = {x["code"]: x["available"] for x in client.get("/api/v1/metrics").json()["items"]}
    assert m["NEAREST_FIN_DIST_M"] and not m["AGED65_PPLTN"]      # KOSIS 미적재 → 지표 비활성


def test_facility_search_escapes_wildcards(client):
    assert client.get("/api/v1/facilities", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/v1/facilities", params={"q": "_"}).json()["total"] == 0
    assert client.get("/api/v1/facilities", params={"q": "F1"}).json()["total"] == 1


def test_not_found_and_validation(client):
    assert client.get(f"/api/v1/whatif/{NIL}/geojson").status_code == 404
    assert client.get("/api/v1/dq/summary", params={"calcRunId": NIL}).status_code == 404
    assert client.get("/api/v1/dq/summary", params={"collectRunId": NIL}).status_code == 404
    assert client.get("/api/v1/dq/issues", params={"severity": "X"}).status_code == 400
    assert client.get("/api/v1/dq/issues", params={"scope": "nope"}).status_code == 400
    r = client.get("/api/v1/areas/geojson", params={"level": 3, "metric": "HAS_365"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR" and r.json()["traceId"]


def test_whatif_roundtrip(client, terrain):
    r = client.post("/api/v1/whatif", json={"removeHistIds": [terrain["F2"]], "level": 2})
    assert r.status_code == 200
    sid = r.json()["scenarioId"]
    assert client.get(f"/api/v1/whatif/{sid}").json()["summary"]["affectedAreas"] == 2
    assert len(client.get(f"/api/v1/whatif/{sid}/geojson").json()["features"]) == 2


def test_calc_finished_at_is_real_end_time(client, engine):
    """finished_at 이 트랜잭션 시작 시각(now())이 아니라 실제 끝난 시각이어야 함."""
    with engine.connect() as c:
        created, finished, ms = c.execute(text("""SELECT created_at, finished_at, (stats->>'elapsedMs')::int
                                                 FROM mart.calc_run WHERE calc_run_id = :r"""), {"r": client.rid}).one()
    assert (finished - created).total_seconds() * 1000 >= ms * 0.9


def test_out_of_range_inputs_are_400_not_500(client):
    """fuzz 로 찾은 버그 — 아주 큰 숫자가 DB 의 bigint/smallint 범위를 넘어 500 이 나던 경로들."""
    huge = "99999999999999999999"
    for path in (f"/api/v1/meta/collect-runs?page={huge}", f"/api/v1/facilities?page={huge}",
                 f"/api/v1/facilities?types={huge}", f"/api/v1/hubs/facilities?page={huge}", "/api/v1/facilities?types=0,42"):
        r = client.get(path)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", path
    # 안전망: 검사를 빠져나간 범위 초과도 DB DataError → 400
    r = client.post("/api/v1/whatif", json={"removeHistIds": [int(huge)], "level": 2})
    assert r.status_code in (400, 404) and r.json()["code"] != "INTERNAL"


def test_geojson_free_inputs_are_bounded(client):
    """parent 는 지역 코드 형식만 (LIKE 와일드카드로 레벨 제한 우회·캐시 키 폭증 방지), simplify 는 정해진 단계로 묶음 (S3)."""
    for bad in ("%", "9_", "abc", "99%", "1234567"):
        r = client.get("/api/v1/areas/geojson", params={"level": 2, "metric": "NEAREST_FIN_DIST_M", "parent": bad})
        assert r.status_code == 400, bad
        assert client.get("/api/v1/areas", params={"level": 2, "parent": bad}).status_code == 400, bad
    assert client.get("/api/v1/areas/geojson", params={"level": 2, "metric": "NEAREST_FIN_DIST_M", "parent": "99"}).status_code == 200
    from atlas.features.areas.service import simplify_step

    assert simplify_step(123.4567) == simplify_step(120.0) == 100.0
    assert simplify_step(0) == 0.0 and simplify_step(None) is None and simplify_step(4.9) == 10.0   # 0 초과는 최소 10m
    assert client.get("/api/v1/visit/conditions", params={"sido": "%"}).status_code == 400   # 값마다 판정 300ms 방지


@pytest.mark.skipif(not __import__("os").environ.get("TEST_REDIS_URL"), reason="캐시 동작은 Redis 필요 (make test 는 켬)")
def test_cache_follows_data_version_without_invalidation(client, engine):
    """지도·개요 캐시 키에 (계산 실행, 도보 완료 시각)이 들어가 — 도보 계산이 끝나면 캐시를 지우지 않아도 새 값 (R4).
    예전에는 커밋 뒤 캐시 지우기에 의존해, 그 사이 읽은 요청이 낡은 값을 다시 쓰면 다음 계산까지(GeoJSON 은 만료 없이) 남았음."""
    p = {"level": 2, "metric": "NEAREST_FIN_DIST_M"}
    val = lambda fc: next(f["properties"]["value"] for f in fc["features"] if f["id"] == "99010")  # noqa: E731
    before = val(client.get("/api/v1/areas/geojson", params=p).json())
    assert client.get("/api/v1/overview").json()["walk"] is None
    with engine.begin() as c:                      # 도보 계산이 끝난 것처럼 (캐시 지우기는 부르지 않음)
        c.execute(text("""UPDATE mart.access_metric SET value = value + 1
                           WHERE calc_run_id = :r AND metric_code = 'NEAREST_FIN_DIST_M' AND adm_cd = '99010'"""),
                  {"r": client.rid})
        c.execute(text("""INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
                          VALUES (:r, '99010', 'WALK30_NO_FIN_PPLTN', 2, 10)"""), {"r": client.rid})
        c.execute(text("""INSERT INTO mart.walk_run (calc_run_id, status, speed_mps, limit_m, finished_at)
                          VALUES (:r, 'DONE', 0.8, 3000, now())"""), {"r": client.rid})
    assert val(client.get("/api/v1/areas/geojson", params=p).json()) == before + 1
    assert client.get("/api/v1/overview").json()["walk"]["noFinPpltn"] == 10


def test_overview_far_threshold_follows_calc_params(terrain, engine):
    """개요의 '먼 거리' 인구가 계산 설정(farKm)과 같은 기준 — 예전에는 집계구 값만 설정을 따르고 나머지는 2km 고정 (R10)."""
    from atlas.api.main import app

    rid = run_calc(stat_year=2024, levels=[2], params={"farKm": 3})
    with engine.connect() as c:
        expect = c.execute(text("""SELECT coalesce(sum(p.tot_ppltn), 0) FROM mart.access_metric m
                                     JOIN mart.area_population p ON p.adm_cd = m.adm_cd AND p.stat_year = 2024
                                    WHERE m.calc_run_id = :r AND m.metric_code = 'NEAREST_FIN_DIST_M' AND m.level = 2
                                      AND m.value > 3000"""), {"r": rid}).scalar()
    with TestClient(app) as c:
        ov = c.get("/api/v1/overview").json()
    assert ov["farKm"] == 3 and ov["farPpltn"] == expect


def test_geojson_explicit_default_simplify_shares_cache(client, monkeypatch):
    """기본값과 같은 simplify(시군구 200m)를 적은 요청은 생략한 요청과 같은 캐시 항목을 씀 — 같은 본문을 두 번 만들어 두지 않게."""
    from atlas.core import cache

    store: dict[str, bytes] = {}
    monkeypatch.setattr(cache, "get", lambda k: store.get(k))
    monkeypatch.setattr(cache, "set", lambda k, v, ttl=None: store.__setitem__(k, v if isinstance(v, bytes) else v.encode()))
    p = {"level": 2, "metric": "NEAREST_FIN_DIST_M"}
    a = client.get("/api/v1/areas/geojson", params=p)
    b = client.get("/api/v1/areas/geojson", params={**p, "simplify": 200})
    assert a.status_code == b.status_code == 200 and a.content == b.content
    assert len([k for k in store if not k.endswith(":etag")]) == 1


@pytest.mark.parametrize("path", ["/api/v1/visit/conditions?sido=١١", "/api/v1/banks/impact?sido=١١",
                                  "/api/v1/banks/impact?sgg=１１１１１", "/api/v1/hubs/facilities?sido=１１",
                                  "/api/v1/areas/１１１１１/report", "/api/v1/visit/conditions/٣٧٥٢٠"])
def test_region_codes_reject_non_ascii_digits(client, path):
    """지역 코드 검사가 7곳에 따로 있어 갈라졌음 — 같은 '١١'(아랍 숫자)에 400·404·200 이 제각각이었고, 200 인 곳은 값마다
    30분 캐시 항목이 새로 생겼음. 이제 모두 ASCII 숫자만 받고 400 VALIDATION_ERROR."""
    r = client.get(path)
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", (path, r.status_code, r.text[:200])


def test_plan_scope_rejects_non_ascii_digits(client):
    r = client.post("/api/v1/plan/close", json={"scope": "²²", "k": 1, "weight": "aged65"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


def test_facility_status_during_lunch_break(client, engine, terrain, monkeypatch):
    """점심 휴무 우체국의 상세 상태 — 점심시간이면 'lunch'(화면은 '영업 중' 초록이 아님)."""
    from datetime import datetime

    from atlas.features import facilities

    with engine.begin() as c:
        c.execute(text("UPDATE mart.post_facility_hist SET lunch_time = '12:00~13:00' WHERE hist_id = :h"), {"h": terrain["F2"]})
    monkeypatch.setattr(facilities, "now_kst", lambda: datetime(2026, 9, 29, 12, 10))
    st = client.get(f"/api/v1/facilities/{terrain['F2']}").json()["status"]
    assert st["state"] == "lunch" and "13:00" in st["label"]


@pytest.mark.parametrize("body", [b'{"removeHistIds":["\xff"]}', b"[" * 10000])
def test_unparseable_body_is_validation_error(client, body):
    """본문을 해석할 수 없으면(UTF-8 오류·깊은 중첩) 다른 잘못된 JSON 과 같은 400 VALIDATION_ERROR·한국어 — 예전에는 FastAPI 가
    낸 400 이 코드 표에 없어 HTTP_ERROR·'There was an error parsing the body' 로 나가 클라이언트가 코드로 구분할 수 없었음."""
    r = client.post("/api/v1/whatif", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"
    assert "parsing" not in r.json()["message"]
