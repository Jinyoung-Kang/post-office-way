"""라우터·서비스 공통 — 지표 정의 조회, 시설 열·응답 모양."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.core.serial import jsonable
from atlas.domain.errors import NotFound
from atlas.domain.rules import POST_DIV_LABEL


def metric_row(c: Connection, code: str) -> dict[str, Any]:
    r = c.execute(text("SELECT * FROM mart.metric_def WHERE metric_code = :c"), {"c": code}).mappings().first()
    if not r:
        raise NotFound("METRIC_NOT_FOUND", f"지표 {code} 가 없습니다.")
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
