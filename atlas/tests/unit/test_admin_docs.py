"""관리 API 문서(/docs)의 작업 종류 목록이 실제 작업(registry.JOBS)과 같은지 — 손으로 적던 목록이 5종(sgis-pop·sgis-bnd·
banks-full·osm·walk) 빠진 채 남아 있었음 (2차 리뷰 O5)."""
from atlas.api.main import app
from atlas.jobs.registry import JOBS


def test_admin_job_summary_lists_every_kind():
    s = next(op["summary"] for p, ops in app.openapi()["paths"].items() if p.endswith("/admin/jobs")
             for m, op in ops.items() if m == "post")
    assert all(k in s.split("kind: ")[1] for k in JOBS)
