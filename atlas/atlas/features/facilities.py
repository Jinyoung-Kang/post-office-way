"""시설(우체국) 목록·상세 — 조회 열(FACILITY_COLS)과 응답 모양(facility_json)은 지역 상세도 같이 씀."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.core.clock import now_kst
from atlas.core.serial import jsonable
from atlas.domain.calendar import business_status
from atlas.domain.errors import Invalid, NotFound
from atlas.domain.params import page_params, parse_bbox
from atlas.domain.rules import POST_DIV_LABEL
from atlas.features import calendar, hubs

BBOX_MAX_SIZE = 5000  # 지도 레이어용(bbox 지정 시)만 크게 허용


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


def list_facilities(c: Connection, bbox: str | None, types: str | None, fin_only: bool, q: str | None,
                    page: int, size: int) -> dict[str, Any]:
    page, size, off = page_params(page, size, cap=BBOX_MAX_SIZE if bbox else 200)
    where = ["h.is_current"]
    p: dict = {"lim": size, "off": off}
    if bbox:
        x1, y1, x2, y2 = parse_bbox(bbox)
        where.append("h.geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)")
        p.update(x1=x1, y1=y1, x2=x2, y2=y2)
    if types:
        try:
            p["types"] = [int(t) for t in types.split(",") if t.strip()]
            if any(not 0 <= t <= 9 for t in p["types"]):
                raise ValueError("post_div 범위 밖")
        except ValueError as e:
            raise Invalid("types 는 숫자 목록입니다 (0 총괄국 · 1 우체국 · 2 우체통 · 3 365코너 · 4 무인창구 · 5 우표판매소).") from e
        where.append("h.post_div = ANY(CAST(:types AS smallint[]))")
    if fin_only:
        where.append("h.fin_available")
    if q and q.strip():
        # 사용자가 입력한 % _ \ 는 글자 그대로 찾도록 이스케이프 (안 하면 '%' 검색이 전체를 반환)
        esc = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(h.name ILIKE :q ESCAPE '\\' OR h.addr ILIKE :q ESCAPE '\\')")
        p["q"] = f"%{esc}%"
    w = " AND ".join(where)          # 고정 조각만 이어 붙이고 값은 모두 바인드 변수
    total = c.execute(text(f"SELECT count(*) FROM mart.post_facility_hist h WHERE {w}"), p).scalar_one()
    rows = c.execute(text(f"""SELECT {FACILITY_COLS} FROM mart.post_facility_hist h WHERE {w}
                              ORDER BY h.post_div, h.name, h.hist_id LIMIT :lim OFFSET :off"""), p).mappings().all()
    return {"items": [facility_json(dict(r)) for r in rows], "page": page, "size": size, "total": total}


def facility_detail(c: Connection, hist_id: int) -> dict[str, Any]:
    r = c.execute(text(f"SELECT {FACILITY_COLS}, h.valid_to FROM mart.post_facility_hist h WHERE h.hist_id = :id"),
                  {"id": hist_id}).mappings().first()
    if not r:
        raise NotFound("FACILITY_NOT_FOUND", f"histId {hist_id} 가 없습니다.")
    areas = c.execute(text("""
        SELECT m.level, m.adm_cd, a.adm_nm, m.method, m.stat_year
          FROM mart.facility_area_map m
          JOIN mart.admin_area a ON a.adm_cd = m.adm_cd AND a.stat_year = m.stat_year
         WHERE m.hist_id = :id ORDER BY m.stat_year DESC, m.level"""), {"id": hist_id}).mappings().all()
    geo = c.execute(text("""SELECT status, dist_m, addr_lat, addr_lon, checked_at FROM mart.facility_geocheck
                             WHERE post_id = :pid"""), {"pid": r["post_id"]}).mappings().first()
    history = c.execute(text("""
        SELECT hist_id, valid_from, valid_to, is_current, finance_time, fin_available FROM mart.post_facility_hist
         WHERE post_id = :pid ORDER BY valid_from DESC"""), {"pid": r["post_id"]}).mappings().all()
    hub = hubs.facility_hub(c, hist_id)
    now = now_kst()
    hol = calendar.holidays(c, now.date(), now.date())
    out = facility_json(dict(r))
    out["hub"] = hub
    out["status"] = business_status(r["finance_time"], now, hol) if r["fin_available"] else None
    out["validTo"] = jsonable(r["valid_to"])
    out["coordSource"] = r["coord_source"]
    out["geocheck"] = jsonable({"status": geo["status"], "distM": geo["dist_m"], "addrLat": geo["addr_lat"],
                                "addrLon": geo["addr_lon"], "checkedAt": geo["checked_at"]}) if geo else None
    out["areas"] = [jsonable({"level": a["level"], "admCd": a["adm_cd"], "admNm": a["adm_nm"],
                              "method": a["method"], "statYear": a["stat_year"]}) for a in areas]
    out["history"] = [jsonable({"histId": h["hist_id"], "validFrom": h["valid_from"], "validTo": h["valid_to"],
                                "isCurrent": h["is_current"], "financeTime": h["finance_time"],
                                "finAvailable": h["fin_available"]}) for h in history]
    return out
