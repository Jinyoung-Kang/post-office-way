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
