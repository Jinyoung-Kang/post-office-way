"""도메인 오류 → HTTP 상태·본문 — 서비스는 상태 코드를 모르고, api/errors.py 한 곳에서 바꿈."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api import errors
from atlas.domain.errors import Conflict, Invalid, NotFound

app = FastAPI()
errors.install(app)
RAISE = {"invalid": Invalid("level 이 잘못됨"), "missing": NotFound("AREA_NOT_FOUND", "없음"),
         "busy": Conflict("CALC_RUN_NOT_DONE", "계산 중")}


@app.get("/{what}")
def _raise(what: str):
    raise RAISE[what]


@pytest.mark.parametrize("what,status,code", [("invalid", 400, "VALIDATION_ERROR"), ("missing", 404, "AREA_NOT_FOUND"),
                                              ("busy", 409, "CALC_RUN_NOT_DONE")])
def test_domain_error_status(what, status, code):
    r = TestClient(app).get(f"/{what}")
    assert r.status_code == status
    body = r.json()
    assert body["code"] == code and body["message"] == RAISE[what].message and "traceId" in body
