"""메타 정보 — 수집·계산 실행 목록, 시도·시군구 목록, 지표 정의 (화면의 선택 목록·설명·운영 화면)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.calc.runs import LATEST_DONE_ID, latest_done
from atlas.core.config import get_settings
from atlas.core.masking import safe_error
from atlas.core.serial import jsonable
from atlas.domain.params import page_params
from atlas.domain.rules import RULE_VERSION

FIN_RULE = {
    "code": "R-FIN-01", "version": RULE_VERSION, "name": "금융 가능 시설 판정",
    "conditions": [
        "post_div ∈ {0, 1} (총괄국·소속 우체국)",
        "금융 서비스시간(postFinanceTime)이 HH:MM~HH:MM 형식",
        "금융 서비스시간 ≠ 00:00~00:00 (명세 예시의 우편취급국 값 — '금융 미제공'으로 해석. 실데이터에서 취급국 54곳이 이 값)",
        "우편집중국이 아님 (지역코드 c 접두 또는 이름에 '우편집중국')",
    ],
}
DISCLAIMER = ("이 페이지의 지표는 이 프로젝트가 정의한 분석용 지표이며 공식 통계가 아닙니다. "
              "시설 데이터는 수집 시점 현재, 인구는 SGIS 통계 연도·KOSIS 주민등록 기준월 기준이라 시점 차이가 있습니다.")


def collect_runs(c: Connection, kind: str | None, page: int, size: int) -> dict[str, Any]:
    page, size, off = page_params(page, size)
    p = {"k": kind, "lim": size, "off": off}
    where = "WHERE (CAST(:k AS text) IS NULL OR kind = CAST(:k AS text))"
    total = c.execute(text(f"SELECT count(*) FROM ops.collect_run {where}"), p).scalar_one()
    rows = c.execute(text(f"""SELECT collect_run_id, kind, status, scope, started_at, finished_at, stats, error
                              FROM ops.collect_run {where} ORDER BY started_at DESC LIMIT :lim OFFSET :off"""),
                     p).mappings().all()
    items = [jsonable({"collectRunId": r["collect_run_id"], "kind": r["kind"], "status": r["status"],
                       "scope": r["scope"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
                       "stats": _brief_stats(r["stats"]), "error": safe_error(r["error"], 300)}) for r in rows]
    return {"items": items, "page": page, "size": size, "total": total}


def _brief_stats(s: dict | None) -> dict:
    s = dict(s or {})
    for k in ("doneCodes",):  # 수백 개짜리 목록은 개수만
        if isinstance(s.get(k), list):
            s[k] = len(s[k])
    return s


def calc_runs(c: Connection, page: int, size: int) -> dict[str, Any]:
    page, size, off = page_params(page, size)
    total = c.execute(text("SELECT count(*) FROM mart.calc_run")).scalar_one()
    rows = c.execute(text("""SELECT calc_run_id, stat_year, facility_as_of, params, status, stats, error,
                                    created_at, finished_at
                             FROM mart.calc_run ORDER BY created_at DESC LIMIT :lim OFFSET :off"""),
                     {"lim": size, "off": off}).mappings().all()
    items = [jsonable({"calcRunId": r["calc_run_id"], "statYear": r["stat_year"],
                       "facilityAsOf": r["facility_as_of"], "params": r["params"], "status": r["status"],
                       "stats": r["stats"], "error": safe_error(r["error"], 300), "createdAt": r["created_at"],
                       "finishedAt": r["finished_at"]}) for r in rows]
    return {"items": items, "page": page, "size": size, "total": total}


def regions(c: Connection, year: int | None) -> dict[str, Any]:
    # 기본은 최신 계산의 통계 연도 (.env STAT_YEAR 를 바꾸고 아직 계산 전이어도 화면과 어긋나지 않게)
    y = year or (latest_done(c) or {}).get("stat_year") or get_settings().stat_year
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


def metric_catalog(c: Connection) -> dict[str, Any]:
    """지표 정의 목록 — 최신 계산에 실제로 값이 있는지(available)와 값이 있는 단위(levels) 함께
    (KOSIS 미적재면 고령인구 지표는 false, 인구 추세는 시군구[2]만)."""
    rows = c.execute(text("SELECT * FROM mart.metric_def ORDER BY sort_order, metric_code")).mappings().all()
    levels = {r[0]: sorted(r[1]) for r in c.execute(text(f"""
        SELECT metric_code, array_agg(DISTINCT level) FROM mart.access_metric
         WHERE calc_run_id = {LATEST_DONE_ID} AND value IS NOT NULL GROUP BY metric_code"""))}
    return {"items": [{"code": r["metric_code"], "name": r["name_ko"], "unit": r["unit"], "formula": r["formula"],
                       "limitation": r["limitation"], "higherIsWorse": r["higher_is_worse"],
                       "ruleVersion": r["rule_version"], "available": r["metric_code"] in levels,
                       "levels": levels.get(r["metric_code"], [])} for r in rows],
            "finRule": FIN_RULE, "disclaimer": DISCLAIMER}
