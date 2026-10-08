"""API 응답 고정(스냅숏) — 구조 리팩터링(라우터·서비스·쿼리 나누기)이 응답을 바꾸지 않았는지 확인.

소형 지형 + 집계구 + 은행 지점 + 계산 + 도보(500m 격자 그래프)로 주요 엔드포인트를 부르고, 매번 달라지는 값(UUID·시각)만
바꿔 tests/sql/snapshots/*.json 과 비교합니다. 의도해서 응답을 바꿨다면 UPDATE_SNAPSHOTS=1 로 다시 저장하고 diff 를 검토하세요.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.sql.test_bank_impact import impact  # noqa: F401 — 픽스처
from tests.sql.test_walk_compute import grid_graph

pytest.importorskip("scipy")
pytestmark = pytest.mark.db
SNAP = Path(__file__).parent / "snapshots"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _norm(v):
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, str):
        if _TS.match(v):
            return "<ts>"
        return _UUID.sub("<uuid>", v)
    if isinstance(v, float):
        return round(v, 3)
    return v


def _check(name: str, body) -> None:
    got = _norm(body)
    path = SNAP / f"{name}.json"
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        if not os.environ.get("UPDATE_SNAPSHOTS"):
            pytest.fail(f"스냅숏 {name} 을 새로 만들었습니다 — 내용을 검토하고 다시 실행하세요")
    assert got == json.loads(path.read_text()), f"{name} 응답이 스냅숏과 다릅니다"


@pytest.fixture()
def world(impact, engine, terrain):  # noqa: F811
    from atlas.walk.compute import run_walk

    rid, _ = impact
    run_walk(str(rid), graph=grid_graph(engine))
    from atlas.api.main import app

    with TestClient(app) as c:
        c.terrain = terrain
        yield c


CASES = [
    ("overview", "GET", "/api/v1/overview", None),
    ("areas_list", "GET", "/api/v1/areas?level=2&metric=NEAREST_FIN_DIST_M", None),
    ("areas_geojson", "GET", "/api/v1/areas/geojson?level=2&metric=WALK30_NO_FIN_PPLTN", None),
    ("area_detail", "GET", "/api/v1/areas/99010", None),
    ("area_report", "GET", "/api/v1/areas/99010/report", None),
    ("bank_impact_list", "GET", "/api/v1/banks/impact", None),
    ("bank_impact_detail", "GET", "/api/v1/banks/impact/K1", None),
    ("bank_impact_geojson", "GET", "/api/v1/banks/impact/K1/geojson", None),
    ("hubs_summary", "GET", "/api/v1/hubs/summary", None),
    ("hubs_facilities", "GET", "/api/v1/hubs/facilities", None),
    ("meta_regions", "GET", "/api/v1/meta/regions", None),
    ("metrics", "GET", "/api/v1/metrics", None),
    ("plan_close", "POST", "/api/v1/plan/close", {"scope": "99", "k": 1}),
    ("plan_open", "POST", "/api/v1/plan/open", {"scope": "99", "k": 1}),
]


@pytest.mark.parametrize("name,method,path,body", CASES, ids=[c[0] for c in CASES])
def test_response_snapshot(world, name, method, path, body):
    r = world.request(method, path, json=body)
    assert r.status_code == 200, r.text
    _check(name, r.json())


def test_whatif_snapshot(world):
    created = world.post("/api/v1/whatif", json={"removeHistIds": [world.terrain["F1"]]}).json()
    _check("whatif_create", created)
    sid = created["scenarioId"]
    _check("whatif_get", world.get(f"/api/v1/whatif/{sid}").json())
    _check("whatif_geojson", world.get(f"/api/v1/whatif/{sid}/geojson").json())
