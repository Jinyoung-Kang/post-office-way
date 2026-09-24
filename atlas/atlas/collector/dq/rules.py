"""데이터 품질 규칙 (설계서 9장). 규칙마다 '실행했음'을 ops.dq_check 에 남기고,
걸린 행은 ops.dq_issue 에 다시 찾을 수 있는 키와 함께 저장합니다 (FR-601).

SQL 규칙은 INSERT … SELECT 로 한 번에 기록하고 건수를 돌려받습니다.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

# 코드 → (심각도, 설명)
RULES: dict[str, tuple[str, str]] = {
    "COORD_NULL": ("ERROR", "위도·경도가 없고 주소로도 채우지 못함"),
    "COORD_OUT_OF_KR": ("ERROR", "위도 33~39, 경도 124~132 밖"),
    "DUP_POST_ID": ("ERROR", "같은 run 에서 post_id 중복"),
    "TOTALCOUNT_MISMATCH": ("WARN", "지역별 적재 건수 ≠ totalCount"),
    "TIME_FORMAT": ("WARN", "운영·금융·점심 시간 문자열이 HH:MM~HH:MM 아님"),
    "STALE_MOD_DT": ("INFO", "modDt 가 3년 이상 전"),
    "FETCH_FAILED": ("WARN", "재시도 후에도 실패한 호출 (지역코드 단위)"),
    "SPATIAL_JOIN_MISS": ("WARN", "어느 행정구역에도 포함되지 않는 시설 (근접 보정 포함)"),
    "GEOM_INVALID": ("ERROR", "ST_IsValid(geom) = false"),
    "POP_NULL": ("WARN", "인구 주요지표 tot_ppltn / aged_child_idx 가 비어 있음"),
    "AREA_WITHOUT_POP": ("INFO", "경계는 있으나 같은 연도 인구 지표가 없는 지역"),
    "REP_POINT_OUTSIDE": ("ERROR", "대표점이 자기 폴리곤 밖"),
    "KOSIS_UNMATCHED": ("INFO", "KOSIS 주민등록인구와 이름으로 맞추지 못한 SGIS 행정구역"),
    "COORD_GEOCODED": ("INFO", "API 좌표가 없어 주소 검색(카카오)으로 채운 시설"),
    "COORD_ADDR_MISMATCH": ("WARN", "API 좌표와 주소 검색 좌표가 1km 넘게 다름"),
    "ADDR_NOT_FOUND": ("INFO", "주소 검색(카카오)으로 찾지 못한 시설 주소"),
    "OA_UNMATCHED": ("INFO", "집계구 인구·경계 중 한쪽만 있는 집계구"),
}

COLLECT_POST_RULES = ("COORD_NULL", "COORD_GEOCODED", "COORD_OUT_OF_KR", "DUP_POST_ID", "TOTALCOUNT_MISMATCH",
                      "TIME_FORMAT", "STALE_MOD_DT", "FETCH_FAILED")
COLLECT_SGIS_RULES = ("GEOM_INVALID", "REP_POINT_OUTSIDE", "POP_NULL", "AREA_WITHOUT_POP", "FETCH_FAILED")
CALC_RULES = ("SPATIAL_JOIN_MISS", "GEOM_INVALID")


@dataclass
class DQRecorder:
    """collect_run 또는 calc_run 한쪽에 묶어 기록합니다."""

    collect_run_id: uuid.UUID | None = None
    calc_run_id: uuid.UUID | None = None

    def _ids(self) -> dict[str, Any]:
        return {"crun": self.collect_run_id, "calc": self.calc_run_id}

    def add(self, conn: Connection, code: str, table: str | None, key: str | None,
            detail: dict[str, Any] | None = None) -> None:
        conn.execute(text("""INSERT INTO ops.dq_issue
                (collect_run_id, calc_run_id, check_code, severity, target_table, target_key, detail)
                VALUES (:crun, :calc, :code, :sev, :tbl, :key, CAST(:d AS jsonb))"""),
                {**self._ids(), "code": code, "sev": RULES[code][0], "tbl": table, "key": key,
                 "d": json.dumps(detail or {}, ensure_ascii=False, default=str)})

    def add_sql(self, conn: Connection, code: str, table: str, select_sql: str,
                params: dict[str, Any] | None = None) -> int:
        """select_sql 은 (target_key text, detail jsonb) 두 컬럼을 돌려줘야 합니다."""
        res = conn.execute(text(f"""INSERT INTO ops.dq_issue
                (collect_run_id, calc_run_id, check_code, severity, target_table, target_key, detail)
                SELECT CAST(:crun AS uuid), CAST(:calc AS uuid), :code, :sev, :tbl, q.target_key, q.detail
                FROM ({select_sql}) AS q(target_key, detail)"""),
                {**(params or {}), **self._ids(), "code": code, "sev": RULES[code][0], "tbl": table})
        return res.rowcount or 0

    def record_checks(self, conn: Connection, codes: tuple[str, ...]) -> dict[str, int]:
        """규칙별 건수를 이슈 테이블에서 집계해 dq_check 에 남깁니다 (0건도 기록)."""
        counts: dict[str, int] = {}
        where = ("collect_run_id = :crun" if self.collect_run_id else "calc_run_id = :calc")
        # 재개(resume)로 같은 run 을 다시 마감할 때 중복 기록 방지
        conn.execute(text(f"DELETE FROM ops.dq_check WHERE {where} AND check_code = ANY(CAST(:codes AS text[]))"),
                     {**self._ids(), "codes": list(codes)})
        for code in codes:
            n = conn.execute(text(f"SELECT count(*) FROM ops.dq_issue WHERE {where} AND check_code = :code"),
                             {**self._ids(), "code": code}).scalar_one()
            conn.execute(text("""INSERT INTO ops.dq_check (collect_run_id, calc_run_id, check_code, severity, issue_count)
                                 VALUES (:crun, :calc, :code, :sev, :n)"""),
                         {**self._ids(), "code": code, "sev": RULES[code][0], "n": n})
            counts[code] = n
        return counts
