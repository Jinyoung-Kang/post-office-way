"""요청 본문 상한 (S2) — 인증·검증 전에 큰 본문을 메모리에 다 올리지 않음. DB 없이 미들웨어만 시험."""
from fastapi.testclient import TestClient

from atlas.api.main import app

client = TestClient(app)
BIG = b'{"kind": "calc", "params": {"x": "' + b"a" * 200_000 + b'"}}'


def test_large_body_rejected_before_auth():
    r = client.post("/api/v1/admin/jobs", content=BIG, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    body = r.json()
    assert body["code"] == "PAYLOAD_TOO_LARGE" and body["traceId"]


def test_large_chunked_body_rejected():
    def chunks():
        for _ in range(50):
            yield b"a" * 10_000

    r = client.post("/api/v1/admin/jobs", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_whatif_ids_capped_by_schema():
    r = client.post("/api/v1/whatif", json={"removeHistIds": list(range(1, 501))})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"
