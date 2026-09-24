"""관리 API — 수집·계산 트리거. X-Admin-Token 필수. 작업은 백그라운드로 돌리고 즉시 202 를 반환."""
from __future__ import annotations

import hmac
import logging
import threading

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from atlas.api.errors import ApiError
from atlas.calc.runner import CalcRunInProgress, create_calc_run, execute_calc_run
from atlas.collector import runs
from atlas.core.config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger(__name__)

KINDS = {"post": "POST_AREA", "sgis-pop": "SGIS_POP", "sgis-bnd": "SGIS_BND", "kosis": "KOSIS_POP",
         "oa": "SGIS_OA", "geocheck": "KAKAO_GEO", "banks": "KAKAO_BANK", "road": "KAKAO_ROAD"}


def _auth(token: str | None) -> None:
    expected = get_settings().admin_token
    if not expected:
        raise ApiError(503, "ADMIN_DISABLED", ".env 에 ADMIN_TOKEN 이 없어 관리 API 가 꺼져 있습니다.")
    if not token or not hmac.compare_digest(token, expected):
        raise ApiError(401, "UNAUTHORIZED", "X-Admin-Token 이 일치하지 않습니다.")


def _bg(name: str, fn, *args) -> None:
    def run() -> None:
        try:
            fn(*args)
        except Exception:  # 결과는 collect_run / calc_run 에 FAILED 로 남습니다
            log.exception("admin job failed", extra={"job": name})

    threading.Thread(target=run, name=name, daemon=True).start()


@router.post("/collect/{kind}", status_code=202, summary="수집 실행 트리거 (FR-101, FR-202)")
def trigger_collect(kind: str, scope: str | None = None, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    if kind not in KINDS:
        raise ApiError(400, "VALIDATION_ERROR", f"kind 는 {list(KINDS)} 중 하나입니다.")
    run_kind = KINDS[kind]
    if rid := runs.running_run(run_kind):
        raise ApiError(409, "RUN_IN_PROGRESS", f"{run_kind} 수집이 이미 실행 중입니다 (collectRunId={rid}).")
    codes = [x.strip() for x in scope.split(",")] if scope and scope != "all" else None

    if kind == "post":
        from atlas.collector.post.pipeline import collect_post

        _bg("collect-post", collect_post, codes)
    elif kind == "kosis":
        from atlas.collector.kosis.pipeline import collect_kosis

        if not get_settings().kosis_api_key:
            raise ApiError(400, "KEY_MISSING", ".env 에 KOSIS_API_KEY 가 없습니다.")
        _bg("collect-kosis", collect_kosis)
    elif kind in ("oa", "geocheck", "banks", "road"):
        if kind != "oa" and not get_settings().kakao_rest_api_key:
            raise ApiError(400, "KEY_MISSING", ".env 에 KAKAO_REST_API_KEY 가 없습니다.")
        from atlas.collector.kakao.banks import collect_banks
        from atlas.collector.kakao.geocheck import run_geocheck
        from atlas.collector.kakao.road import collect_road
        from atlas.collector.sgis.oa import collect_oa

        _bg(f"collect-{kind}", {"oa": collect_oa, "geocheck": run_geocheck, "banks": collect_banks,
                                "road": collect_road}[kind])
    elif kind == "sgis-pop":
        from atlas.collector.sgis.pipeline import collect_population

        _bg("collect-sgis-pop", collect_population)
    else:
        from atlas.collector.sgis.pipeline import collect_boundaries

        _bg("collect-sgis-bnd", collect_boundaries)
    # run 행은 백그라운드 작업이 만듭니다 — 진행 상황은 GET /meta/collect-runs 로 확인
    return JSONResponse({"kind": run_kind, "status": "QUEUED", "check": "/api/v1/meta/collect-runs"},
                        status_code=202)


class CalcRequest(BaseModel):
    statYear: int | None = None
    levels: list[int] | None = None
    params: dict | None = None


@router.post("/calc", status_code=202, summary="계산 실행 트리거 (FR-303)")
def trigger_calc(req: CalcRequest | None = None, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    req = req or CalcRequest()
    try:
        rid = create_calc_run(req.statYear, req.levels, req.params)
    except CalcRunInProgress as e:
        raise ApiError(409, "RUN_IN_PROGRESS", str(e)) from e
    _bg("calc", execute_calc_run, rid)
    return JSONResponse({"calcRunId": str(rid), "status": "RUNNING"}, status_code=202)
