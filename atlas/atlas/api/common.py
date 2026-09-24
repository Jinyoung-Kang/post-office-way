"""라우터 공통 — calc_run 결정, 메타(calcRunId·statYear·facilityAsOf), 페이지네이션, 직렬화."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api.errors import ApiError, bad_request, not_found
from atlas.domain.rules import POST_DIV_LABEL

MAX_SIZE = 200


def jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def parse_uuid(v: str | None, what: str = "calcRunId") -> uuid.UUID | None:
    if v in (None, ""):
        return None
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise bad_request(f"{what} 형식이 잘못되었습니다: {v}") from e


def resolve_calc_run(c: Connection, calc_run_id: str | None, require_done: bool = True) -> dict[str, Any]:
    """calcRunId 생략 시 최신 DONE calc_run."""
    rid = parse_uuid(calc_run_id)
    if rid:
        r = c.execute(text("""SELECT calc_run_id, stat_year, facility_as_of, params, status, created_at, finished_at
                              FROM mart.calc_run WHERE calc_run_id = :id"""), {"id": rid}).mappings().first()
        if not r:
            raise not_found("CALC_RUN_NOT_FOUND", f"calcRunId {rid} 가 없습니다.")
        if require_done and r["status"] != "DONE":
            raise ApiError(409, "CALC_RUN_NOT_DONE", f"calcRunId {rid} 상태가 {r['status']} 입니다.")
    else:
        r = c.execute(text("""SELECT calc_run_id, stat_year, facility_as_of, params, status, created_at, finished_at
                              FROM mart.calc_run WHERE status = 'DONE'
                              ORDER BY finished_at DESC NULLS LAST, created_at DESC LIMIT 1""")).mappings().first()
        if not r:
            raise not_found("CALC_RUN_NOT_FOUND", "완료된 계산 실행이 없습니다. 수집 후 `make calc` 를 실행하세요.")
    return dict(r)


def meta_of(run: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return jsonable({"calcRunId": run["calc_run_id"], "statYear": run["stat_year"],
                     "facilityAsOf": run["facility_as_of"], **extra})


def page_params(page: int, size: int, cap: int = MAX_SIZE) -> tuple[int, int, int]:
    if page < 1:
        raise bad_request("page 는 1 이상이어야 합니다.")
    if not 1 <= size <= cap:
        raise bad_request(f"size 는 1~{cap} 이어야 합니다.")
    return page, size, (page - 1) * size


def metric_row(c: Connection, code: str) -> dict[str, Any]:
    r = c.execute(text("SELECT * FROM mart.metric_def WHERE metric_code = :c"), {"c": code}).mappings().first()
    if not r:
        raise not_found("METRIC_NOT_FOUND", f"지표 {code} 가 없습니다.")
    return dict(r)


def facility_json(r: dict[str, Any]) -> dict[str, Any]:
    return jsonable({
        "histId": r["hist_id"], "postId": r["post_id"], "name": r["name"], "postDiv": r["post_div"],
        "divLabel": POST_DIV_LABEL.get(r["post_div"], "기타"), "addr": r.get("addr"), "tel": r.get("tel"),
        "lat": r["lat"], "lon": r["lon"], "postTime": r.get("post_time"), "financeTime": r.get("finance_time"),
        "finAvailable": r["fin_available"], "lunchYn": r.get("lunch_yn"), "lunchTime": r.get("lunch_time"),
        "post365Yn": r.get("post365_yn"), "isCenter": r.get("is_center"), "areaCode": r.get("area_code"),
        "modDt": r.get("mod_dt"), "collectedAt": r.get("valid_from"), "isCurrent": r.get("is_current"),
        "coordSource": r.get("coord_source"),
    })


FACILITY_COLS = """h.hist_id, h.post_id, h.name, h.post_div, h.addr, h.tel, ST_Y(h.geom) AS lat, ST_X(h.geom) AS lon,
    h.post_time, h.finance_time, h.fin_available, h.lunch_yn, h.lunch_time, h.post365_yn, h.is_center,
    h.area_code, h.mod_dt, h.valid_from, h.is_current, h.coord_source"""
