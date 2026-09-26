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


@router.get("/jobs", summary="최근 작업 큐 상태 (워커 실행 기록)")
def jobs(limit: int = Query(30, ge=1, le=100)):
    from atlas.jobs import queue

    return {"items": [jsonable({"jobId": j["job_id"], "kind": j["kind"], "status": j["status"], "source": j["source"],
                                "slot": j["slot"], "attempts": j["attempts"], "error": j["error"],
                                "createdAt": j["created_at"], "startedAt": j["started_at"],
                                "finishedAt": j["finished_at"], "result": j["result"]})
                      for j in queue.recent(limit)]}


@router.get("/schedule", summary="워커 스케줄과 다음 실행 시각 (KST)")
def schedule():
    from atlas.core.clock import now_kst
    from atlas.jobs import registry, scheduler

    groups = get_settings().atlas_schedule
    items = scheduler.describe(now_kst(), groups)
    for it in items:
        spec = registry.get(it["kind"])
        it["title"], it["missingKeys"] = spec.title, spec.missing()
    return {"groups": groups, "items": items, "titles": {k: j.title for k, j in registry.JOBS.items()}}


@router.get("/errors", summary="오류 로그 — API 예외·작업·수집·계산 실패·품질 ERROR 를 시간순 한곳에 (복사용 한 줄 포함)")
def errors(days: int = Query(14, ge=1, le=90), limit: int = Query(200, ge=1, le=1000)):
    from atlas.core.masking import brief_error, mask_secrets_in, mask_text

    s = get_settings()
    secrets = [s.post_service_key, s.sgis_consumer_key, s.sgis_consumer_secret, s.kakao_rest_api_key,
               s.kosis_api_key, s.data_go_kr_key, s.admin_token, s.api_db_password]
    with get_engine().connect() as c:
        rows = c.execute(text("""
            SELECT at, source, ref, title, message FROM (
                SELECT at, 'API' AS source, coalesce(trace_id, CAST(error_id AS text)) AS ref,
                       concat(method, ' ', path) AS title, concat(error_type, ': ', message) AS message
                  FROM ops.app_error WHERE at > now() - make_interval(days => :d)
                UNION ALL
                SELECT coalesce(finished_at, created_at), '작업', concat('#', job_id), kind, error
                  FROM ops.job WHERE status = 'FAILED' AND created_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT coalesce(finished_at, started_at), '수집', left(CAST(collect_run_id AS text), 8),
                       concat(kind, ' ', status), error
                  FROM ops.collect_run WHERE status IN ('FAILED', 'PARTIAL') AND error IS NOT NULL
                   AND started_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT coalesce(finished_at, created_at), '계산', left(CAST(calc_run_id AS text), 8), 'calc FAILED', error
                  FROM mart.calc_run WHERE status = 'FAILED' AND created_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT checked_at, '품질', left(CAST(coalesce(collect_run_id, calc_run_id) AS text), 8), check_code,
                       concat('심각도 ERROR 규칙에 걸린 행 ', issue_count, '건')
                  FROM ops.dq_check WHERE severity = 'ERROR' AND issue_count > 0 AND checked_at > now() - make_interval(days => :d)
            ) e ORDER BY at DESC LIMIT :n"""), {"d": days, "n": limit}).mappings().all()
    items = []
    for r in rows:
        msg = mask_secrets_in(mask_text(r["message"] or ""), secrets)
        at = r["at"].astimezone().strftime("%Y-%m-%d %H:%M:%S") if r["at"] else "-"
        items.append({"at": jsonable(r["at"]), "source": r["source"], "ref": r["ref"], "title": r["title"],
                      "message": msg, "line": f"{at} [{r['source']}] {r['ref']} {r['title']} — {brief_error(msg)}"})
    return {"days": days, "items": items, "total": len(items)}

