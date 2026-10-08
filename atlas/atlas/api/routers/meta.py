from __future__ import annotations

from fastapi import APIRouter, Query

from atlas.core.config import get_settings
from atlas.core.db import get_engine
from atlas.core.masking import safe_error
from atlas.core.serial import jsonable
from atlas.features import error_log, meta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/collect-runs", summary="수집 실행 목록(최근순) (FR-601)")
def collect_runs(kind: str | None = None, page: int = 1, size: int = 20):
    with get_engine().connect() as c:
        return meta.collect_runs(c, kind, page, size)


@router.get("/calc-runs", summary="계산 실행 목록 (NFR-07)")
def calc_runs(page: int = 1, size: int = 20):
    with get_engine().connect() as c:
        return meta.calc_runs(c, page, size)


@router.get("/regions", summary="시도 목록 (화면의 읍면동 상위 선택용)")
def regions(year: int | None = Query(None)):
    with get_engine().connect() as c:
        return meta.regions(c, year)


@router.get("/jobs", summary="최근 작업 큐 상태 (워커 실행 기록)")
def jobs(limit: int = Query(30, ge=1, le=100)):
    from atlas.jobs import queue

    return {"items": [jsonable({"jobId": j["job_id"], "kind": j["kind"], "status": j["status"], "source": j["source"],
                                "slot": j["slot"], "attempts": j["attempts"], "error": safe_error(j["error"], 300),
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


@router.get("/errors", summary="오류 로그 — API 예외·작업·수집·계산 실패·품질 ERROR 를 시간순 한곳에 (복사용 한 줄 포함, 지운 항목 제외)")
def errors(days: int = Query(14, ge=1, le=90), limit: int = Query(200, ge=1, le=1000)):
    with get_engine().connect() as c:
        return error_log.list_errors(c, days, limit)
