from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from atlas.api.common import FACILITY_COLS, bad_request, facility_json, jsonable, not_found, page_params
from atlas.api.services import calendar as cal_svc
from atlas.api.services import hubs as hub_svc
from atlas.core.clock import now_kst
from atlas.core.db import get_engine

router = APIRouter(prefix="/facilities", tags=["facilities"])
BBOX_MAX_SIZE = 5000  # 지도 레이어용(bbox 지정 시)만 크게 허용


@router.get("", summary="시설 목록 (bbox, types, finOnly, q, page) (FR-501)")
def list_facilities(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
                    types: str | None = Query(None, description="post_div 목록, 예: 0,1,3"),
                    finOnly: bool = False, q: str | None = None, page: int = 1, size: int = 50):
    page, size, off = page_params(page, size, cap=BBOX_MAX_SIZE if bbox else 200)
    where = ["h.is_current"]
    p: dict = {"lim": size, "off": off}
    if bbox:
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox.split(","))
        except ValueError as e:
            raise bad_request("bbox 는 minLon,minLat,maxLon,maxLat 입니다.") from e
        where.append("h.geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)")
        p.update(x1=x1, y1=y1, x2=x2, y2=y2)
    if types:
        try:
            p["types"] = [int(t) for t in types.split(",") if t.strip()]
        except ValueError as e:
            raise bad_request("types 는 숫자 목록입니다 (0 총괄국 · 1 우체국 · 2 우체통 · 3 365코너 · 4 무인창구 · 5 우표판매소).") from e
        where.append("h.post_div = ANY(CAST(:types AS smallint[]))")
    if finOnly:
        where.append("h.fin_available")
    if q and q.strip():
        # 사용자가 입력한 % _ \ 는 글자 그대로 찾도록 이스케이프 (안 하면 '%' 검색이 전체를 반환)
        esc = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(h.name ILIKE :q ESCAPE '\\' OR h.addr ILIKE :q ESCAPE '\\')")
        p["q"] = f"%{esc}%"
    w = " AND ".join(where)
    with get_engine().connect() as c:
        total = c.execute(text(f"SELECT count(*) FROM mart.post_facility_hist h WHERE {w}"), p).scalar_one()
        rows = c.execute(text(f"""SELECT {FACILITY_COLS} FROM mart.post_facility_hist h WHERE {w}
                                  ORDER BY h.post_div, h.name, h.hist_id LIMIT :lim OFFSET :off"""), p).mappings().all()
    return {"items": [facility_json(dict(r)) for r in rows], "page": page, "size": size, "total": total}


@router.get("/{hist_id}", summary="시설 상세 + 소속 행정구역 (FR-502)")
def facility_detail(hist_id: int):
    with get_engine().connect() as c:
        r = c.execute(text(f"SELECT {FACILITY_COLS}, h.valid_to FROM mart.post_facility_hist h WHERE h.hist_id = :id"),
                      {"id": hist_id}).mappings().first()
        if not r:
            raise not_found("FACILITY_NOT_FOUND", f"histId {hist_id} 가 없습니다.")
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
        hub = hub_svc.facility_hub(c, hist_id)
        now = now_kst()
        hol = cal_svc.holidays(c, now.date(), now.date())
    out = facility_json(dict(r))
    out["hub"] = hub
    out["status"] = cal_svc.business_status(r["finance_time"], now, hol) if r["fin_available"] else None
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
