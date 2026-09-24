from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from atlas.api.common import jsonable, page_params
from atlas.core.config import get_settings
from atlas.core.db import get_engine

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/collect-runs", summary="수집 실행 목록(최근순) (FR-601)")
def collect_runs(kind: str | None = None, page: int = 1, size: int = 20):
    page, size, off = page_params(page, size)
    with get_engine().connect() as c:
        p = {"k": kind, "lim": size, "off": off}
        where = "WHERE (CAST(:k AS text) IS NULL OR kind = CAST(:k AS text))"
        total = c.execute(text(f"SELECT count(*) FROM ops.collect_run {where}"), p).scalar_one()
        rows = c.execute(text(f"""SELECT collect_run_id, kind, status, scope, started_at, finished_at, stats, error
                                  FROM ops.collect_run {where} ORDER BY started_at DESC LIMIT :lim OFFSET :off"""),
                         p).mappings().all()
    items = [jsonable({"collectRunId": r["collect_run_id"], "kind": r["kind"], "status": r["status"],
                       "scope": r["scope"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
                       "stats": _brief_stats(r["stats"]), "error": r["error"]}) for r in rows]
    return {"items": items, "page": page, "size": size, "total": total}


def _brief_stats(s: dict | None) -> dict:
    s = dict(s or {})
    for k in ("doneCodes",):  # 수백 개짜리 목록은 개수만
        if isinstance(s.get(k), list):
            s[k] = len(s[k])
    return s


@router.get("/calc-runs", summary="계산 실행 목록 (NFR-07)")
def calc_runs(page: int = 1, size: int = 20):
    page, size, off = page_params(page, size)
    with get_engine().connect() as c:
        total = c.execute(text("SELECT count(*) FROM mart.calc_run")).scalar_one()
        rows = c.execute(text("""SELECT calc_run_id, stat_year, facility_as_of, params, status, stats, error,
                                        created_at, finished_at
                                 FROM mart.calc_run ORDER BY created_at DESC LIMIT :lim OFFSET :off"""),
                         {"lim": size, "off": off}).mappings().all()
    items = [jsonable({"calcRunId": r["calc_run_id"], "statYear": r["stat_year"],
                       "facilityAsOf": r["facility_as_of"], "params": r["params"], "status": r["status"],
                       "stats": r["stats"], "error": r["error"], "createdAt": r["created_at"],
                       "finishedAt": r["finished_at"]}) for r in rows]
    return {"items": items, "page": page, "size": size, "total": total}


@router.get("/regions", summary="시도 목록 (화면의 읍면동 상위 선택용)")
def regions(year: int | None = Query(None)):
    with get_engine().connect() as c:
        # 기본은 최신 계산의 통계 연도 (.env STAT_YEAR 를 바꾸고 아직 계산 전이어도 화면과 어긋나지 않게)
        y = year or c.execute(text("""SELECT stat_year FROM mart.calc_run WHERE status = 'DONE'
                                      ORDER BY finished_at DESC NULLS LAST LIMIT 1""")).scalar() or get_settings().stat_year
        rows = c.execute(text("""
            SELECT left(a.adm_cd, 2) AS sido, coalesce(p.adm_nm, left(a.adm_cd, 2)) AS nm,
                   count(*) FILTER (WHERE a.level = 2) AS sgg, count(*) FILTER (WHERE a.level = 3) AS emd
              FROM mart.admin_area a
              LEFT JOIN mart.area_population p ON p.adm_cd = left(a.adm_cd, 2) AND p.stat_year = a.stat_year
             WHERE a.stat_year = :y GROUP BY 1, 2 ORDER BY 1"""), {"y": y}).mappings().all()
        sgg = c.execute(text("""SELECT adm_cd, adm_nm FROM mart.admin_area WHERE stat_year = :y AND level = 2
                                ORDER BY adm_cd"""), {"y": y}).all()
    return {"statYear": y,
            "items": [{"admCd": r["sido"], "admNm": r["nm"], "sigunguCount": r["sgg"], "emdCount": r["emd"],
                       "sigungu": [{"admCd": s[0], "admNm": s[1]} for s in sgg if s[0].startswith(r["sido"])]}
                      for r in rows]}
