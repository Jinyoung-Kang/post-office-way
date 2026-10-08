"""오류 로그 — API 예외·작업·수집·계산 실패·품질 ERROR 를 시간순 한곳에. 지운(확인한) 항목은 ops.error_ack 로 숨김.

원본(작업·수집·품질 이력)은 지우지 않음. 메시지는 화면에 내보내기 전에 키·토큰을 가림.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.core.clock import KST
from atlas.core.masking import brief_error, known_secrets, mask_secrets_in, mask_text
from atlas.core.serial import jsonable

_ENTRIES = """
            SELECT id, at, source, ref, title, message FROM (
                SELECT concat('api:', error_id) AS id, at, CASE WHEN source = 'csp' THEN '보안 정책' ELSE 'API' END AS source,
                       coalesce(trace_id, CAST(error_id AS text)) AS ref,
                       concat(method, ' ', path) AS title, concat(error_type, ': ', message) AS message
                  FROM ops.app_error WHERE at > now() - make_interval(days => :d)
                UNION ALL
                SELECT concat('job:', job_id), coalesce(finished_at, created_at), '작업', concat('#', job_id), kind, error
                  FROM ops.job WHERE status = 'FAILED' AND created_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT concat('collect:', collect_run_id), coalesce(finished_at, started_at), '수집', left(CAST(collect_run_id AS text), 8),
                       concat(kind, ' ', status), error
                  FROM ops.collect_run WHERE status IN ('FAILED', 'PARTIAL') AND error IS NOT NULL
                   AND started_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT concat('calc:', calc_run_id), coalesce(finished_at, created_at), '계산', left(CAST(calc_run_id AS text), 8), 'calc FAILED', error
                  FROM mart.calc_run WHERE status = 'FAILED' AND created_at > now() - make_interval(days => :d)
                UNION ALL
                SELECT concat('dq:', check_id), checked_at, '품질', left(CAST(coalesce(collect_run_id, calc_run_id) AS text), 8), check_code,
                       concat('심각도 ERROR 규칙에 걸린 행 ', issue_count, '건')
                  FROM ops.dq_check WHERE severity = 'ERROR' AND issue_count > 0 AND checked_at > now() - make_interval(days => :d)
            ) e
             WHERE NOT EXISTS (SELECT 1 FROM ops.error_ack a WHERE a.entry_id = e.id)   -- 지운(확인한) 항목 제외
             ORDER BY at DESC LIMIT :n"""


def list_errors(c: Connection, days: int, limit: int) -> dict[str, Any]:
    secrets = known_secrets()
    rows = c.execute(text(_ENTRIES), {"d": days, "n": limit}).mappings().all()
    items = []
    for r in rows:
        msg = mask_secrets_in(mask_text(r["message"] or ""), secrets)
        at = r["at"].astimezone(KST).strftime("%Y-%m-%d %H:%M:%S") if r["at"] else "-"   # 서비스 기준 시각(프로세스 TZ 아님)
        items.append({"id": r["id"], "at": jsonable(r["at"]), "source": r["source"], "ref": r["ref"], "title": r["title"],
                      "message": msg, "line": f"{at} [{r['source']}] {r['ref']} {r['title']} — {brief_error(msg)}"})
    return {"days": days, "items": items, "total": len(items)}


def ack(c: Connection, ids: list[str], by: str) -> int:
    """확인 표시 — 이미 지운 항목은 건너뜀. 새로 지운 수."""
    return c.execute(text("""
        INSERT INTO ops.error_ack (entry_id, acked_by)
        SELECT DISTINCT unnest(CAST(:ids AS text[])), :by
        ON CONFLICT (entry_id) DO NOTHING"""), {"ids": ids, "by": by[:64]}).rowcount
