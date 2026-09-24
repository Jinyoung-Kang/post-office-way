from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from atlas.api.common import bad_request, jsonable, not_found, page_params, parse_uuid
from atlas.collector.dq.rules import RULES
from atlas.core.db import get_engine

router = APIRouter(prefix="/dq", tags=["dq"])

# 종류별 최신 수집 run + 최신 계산 run — 요약과 이슈 목록의 기본 범위(같은 행이 run 마다 중복 표시되지 않게)
_LATEST_COLLECT = """SELECT DISTINCT ON (kind) collect_run_id FROM ops.collect_run
                     WHERE status <> 'RUNNING' AND kind <> 'POST_DISCOVER' ORDER BY kind, started_at DESC"""
_LATEST_CALC = """SELECT calc_run_id FROM mart.calc_run WHERE status <> 'RUNNING' ORDER BY created_at DESC LIMIT 1"""


@router.get("/summary", summary="품질 요약 — 최근 수집 run(종류별)·계산 run 의 규칙별 건수 (FR-602)")
def summary(collectRunId: str | None = None, calcRunId: str | None = None):
    crid, calcid = parse_uuid(collectRunId, "collectRunId"), parse_uuid(calcRunId)
    with get_engine().connect() as c:
        if crid:
            runs = c.execute(text("""SELECT collect_run_id, kind, status, started_at, finished_at
                                     FROM ops.collect_run WHERE collect_run_id = :id"""), {"id": crid}).mappings().all()
            if not runs:
                raise not_found("COLLECT_RUN_NOT_FOUND", f"collectRunId {crid} 가 없습니다.")
        else:  # 종류별 최신 run
            runs = c.execute(text(f"""SELECT collect_run_id, kind, status, started_at, finished_at
                                      FROM ops.collect_run WHERE collect_run_id IN ({_LATEST_COLLECT})
                                      ORDER BY kind""")).mappings().all()
        blocks = []
        for r in runs:
            checks = c.execute(text("""SELECT check_code, severity, issue_count, checked_at FROM ops.dq_check
                                       WHERE collect_run_id = :id ORDER BY check_id"""),
                               {"id": r["collect_run_id"]}).mappings().all()
            blocks.append(_block("collect", r["collect_run_id"], r["kind"], r["status"], r["finished_at"], checks))
        calc = c.execute(text("""SELECT calc_run_id, status, finished_at FROM mart.calc_run
                                 WHERE (CAST(:id AS uuid) IS NULL AND status <> 'RUNNING') OR calc_run_id = CAST(:id AS uuid)
                                 ORDER BY created_at DESC LIMIT 1"""), {"id": calcid}).mappings().first()
        if calcid and not calc:
            raise not_found("CALC_RUN_NOT_FOUND", f"calcRunId {calcid} 가 없습니다.")
        if calc:
            checks = c.execute(text("""SELECT check_code, severity, issue_count, checked_at FROM ops.dq_check
                                       WHERE calc_run_id = :id ORDER BY check_id"""),
                               {"id": calc["calc_run_id"]}).mappings().all()
            blocks.append(_block("calc", calc["calc_run_id"], "CALC", calc["status"], calc["finished_at"], checks))
    errors = sum(ch["count"] for b in blocks for ch in b["checks"] if ch["severity"] == "ERROR")
    return {"runs": blocks, "errorCount": errors,
            "rules": [{"code": k, "severity": v[0], "description": v[1]} for k, v in RULES.items()]}


def _block(scope, run_id, kind, status, finished_at, checks) -> dict:
    return jsonable({"scope": scope, "runId": run_id, "kind": kind, "status": status, "checkedAt": finished_at,
                     "checks": [{"code": ch["check_code"], "severity": ch["severity"], "count": ch["issue_count"],
                                 "description": RULES.get(ch["check_code"], ("", ""))[1]} for ch in checks]})


@router.get("/issues", summary="품질 이슈 상세 목록 (필터·페이지)")
def issues(collectRunId: str | None = None, calcRunId: str | None = None, checkCode: str | None = None,
           severity: str | None = None, scope: str = "latest", page: int = 1, size: int = 50):
    """scope=latest(기본): run 을 지정하지 않으면 최신 run 들의 이슈만 · scope=all: 과거 run 포함."""
    page, size, off = page_params(page, size)
    if severity is not None and severity not in ("ERROR", "WARN", "INFO"):
        raise bad_request("severity 는 ERROR · WARN · INFO 중 하나입니다.")
    if scope not in ("latest", "all"):
        raise bad_request("scope 는 latest 또는 all 입니다.")
    p = {"crun": parse_uuid(collectRunId, "collectRunId"), "calc": parse_uuid(calcRunId), "code": checkCode,
         "sev": severity, "lim": size, "off": off}
    latest = ""
    if scope == "latest" and not (p["crun"] or p["calc"]):
        latest = f"""AND (collect_run_id IN ({_LATEST_COLLECT}) OR calc_run_id IN ({_LATEST_CALC}))"""
    where = """(CAST(:crun AS uuid) IS NULL OR collect_run_id = CAST(:crun AS uuid))
               AND (CAST(:calc AS uuid) IS NULL OR calc_run_id = CAST(:calc AS uuid))
               AND (CAST(:code AS text) IS NULL OR check_code = CAST(:code AS text))
               AND (CAST(:sev AS text) IS NULL OR severity = CAST(:sev AS text))""" + latest
    with get_engine().connect() as c:
        total = c.execute(text(f"SELECT count(*) FROM ops.dq_issue WHERE {where}"), p).scalar_one()
        rows = c.execute(text(f"""SELECT * FROM ops.dq_issue WHERE {where}
                                  ORDER BY issue_id DESC LIMIT :lim OFFSET :off"""), p).mappings().all()
    return {"items": [jsonable({"issueId": r["issue_id"], "collectRunId": r["collect_run_id"],
                                "calcRunId": r["calc_run_id"], "checkCode": r["check_code"],
                                "severity": r["severity"], "targetTable": r["target_table"],
                                "targetKey": r["target_key"], "detail": r["detail"], "createdAt": r["created_at"]})
                      for r in rows], "page": page, "size": size, "total": total}
