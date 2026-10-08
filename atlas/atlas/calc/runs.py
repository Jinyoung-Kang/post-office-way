"""계산 실행(mart.calc_run) 조회 — '최신 완료 실행'의 정의는 여기 한 곳 (예전에는 7곳에 따로 있었고 동률 처리가 달랐음)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.core.serial import jsonable
from atlas.domain.errors import Conflict, NotFound
from atlas.domain.params import parse_uuid

# 다른 SQL 안에 넣어 쓰는 부분 질의 (스칼라 calc_run_id)
LATEST_DONE_ID = """(SELECT calc_run_id FROM mart.calc_run WHERE status = 'DONE'
                      ORDER BY finished_at DESC NULLS LAST, created_at DESC LIMIT 1)"""
_COLS = "calc_run_id, stat_year, facility_as_of, params, status, created_at, finished_at"


def latest_done(c: Connection) -> dict[str, Any] | None:
    r = c.execute(text(f"SELECT {_COLS} FROM mart.calc_run WHERE calc_run_id = {LATEST_DONE_ID}")).mappings().first()
    return dict(r) if r else None


def resolve_calc_run(c: Connection, calc_run_id: str | None, require_done: bool = True) -> dict[str, Any]:
    """calcRunId 생략 시 최신 DONE calc_run."""
    rid = parse_uuid(calc_run_id)
    if rid:
        r = c.execute(text(f"SELECT {_COLS} FROM mart.calc_run WHERE calc_run_id = :id"), {"id": rid}).mappings().first()
        if not r:
            raise NotFound("CALC_RUN_NOT_FOUND", f"calcRunId {rid} 가 없습니다.")
        if require_done and r["status"] != "DONE":
            raise Conflict("CALC_RUN_NOT_DONE", f"calcRunId {rid} 상태가 {r['status']} 입니다.")
        return dict(r)
    run = latest_done(c)
    if not run:
        raise NotFound("CALC_RUN_NOT_FOUND", "완료된 계산 실행이 없습니다. 수집 후 `make calc` 를 실행하세요.")
    return run


def data_version(c: Connection, run: dict[str, Any]) -> str:
    """계산 결과 캐시의 버전 — (계산 실행, 도보 완료 시각). 도보 계산이 끝나면 지표 값·개요가 바뀌므로 키도 바뀜.
    키가 데이터를 따라가니 계산·도보가 끝난 뒤 캐시를 지울 필요가 없음 — 지우던 방식은 커밋 직전에 읽은 요청이
    지운 뒤에 낡은 값을 다시 써서 다음 계산까지 남을 수 있었음 (R4)."""
    w = walk_finished_at(c, run["calc_run_id"])
    return f"{run['calc_run_id']}:{int(w.timestamp()) if w else 0}"


def walk_finished_at(c: Connection, calc_run_id: Any) -> Any:
    """이 계산 실행의 도보 계산 완료 시각 (없으면 None)."""
    return c.execute(text("SELECT finished_at FROM mart.walk_run WHERE calc_run_id = :r AND status = 'DONE'"),
                     {"r": calc_run_id}).scalar()


def meta_of(run: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return jsonable({"calcRunId": run["calc_run_id"], "statYear": run["stat_year"],
                     "facilityAsOf": run["facility_as_of"], **extra})
