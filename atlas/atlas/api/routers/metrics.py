from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from atlas.core.db import get_engine
from atlas.domain.rules import RULE_VERSION

router = APIRouter(prefix="/metrics", tags=["metrics"])

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


@router.get("", summary="지표 정의 목록 (FR-504)")
def list_metrics():
    with get_engine().connect() as c:
        rows = c.execute(text("SELECT * FROM mart.metric_def ORDER BY sort_order, metric_code")).mappings().all()
        # 최신 calc_run 에 실제로 값이 있는 지표 (KOSIS 미적재면 고령인구 지표는 false)
        avail = {r[0] for r in c.execute(text("""
            SELECT DISTINCT metric_code FROM mart.access_metric
             WHERE calc_run_id = (SELECT calc_run_id FROM mart.calc_run WHERE status = 'DONE'
                                  ORDER BY finished_at DESC NULLS LAST LIMIT 1) AND value IS NOT NULL"""))}
    return {"items": [{"code": r["metric_code"], "name": r["name_ko"], "unit": r["unit"], "formula": r["formula"],
                       "limitation": r["limitation"], "higherIsWorse": r["higher_is_worse"],
                       "ruleVersion": r["rule_version"], "available": r["metric_code"] in avail} for r in rows],
            "finRule": FIN_RULE, "disclaimer": DISCLAIMER}
