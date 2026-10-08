"""시설(우체국) 조회 열과 응답 모양 — 시설 목록·상세와 지역 상세가 같은 모양을 쓰게."""
from __future__ import annotations

from typing import Any

from atlas.core.serial import jsonable
from atlas.domain.rules import POST_DIV_LABEL


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
