"""KOSIS 주민등록인구 적재 — 65세 이상 인구 수(FR-205)를 SGIS 행정구역에 붙입니다.

흐름: 메타(분류 목록) → 시도별 통계자료(시도* 와일드카드, 4만 셀 제한 안) → 지역별 합계·65+ 합
    → 이름으로 SGIS adm_cd 매칭 → mart.area_resident_pop → 품질 검사(KOSIS_UNMATCHED).
기준월은 기본 {STAT_YEAR}12 — SGIS 경계 연도와 행정구역 체계를 맞추기 위함(KOSIS_PERIOD 로 변경).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.dq.rules import DQRecorder
from atlas.collector.http import Fetcher
from atlas.collector.kosis.matching import KosisTree, SgisArea, aged_codes, infer_parent, match
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)
KIND = "KOSIS_POP"


class KosisError(RuntimeError):
    def __init__(self, code: Any, msg: str):
        super().__init__(f"KOSIS err={code}: {msg}")
        self.code, self.msg = str(code), msg


def _json(res) -> Any:
    if not res.ok:
        raise KosisError(res.status, res.error or "HTTP 오류")
    try:
        data = json.loads(res.body)
    except json.JSONDecodeError as e:
        raise KosisError("PARSE", f"JSON 파싱 실패: {e}") from e
    if isinstance(data, dict) and data.get("err"):
        raise KosisError(data.get("err"), data.get("errMsg") or "")
    return data


def fetch_meta(fetcher: Fetcher) -> list[dict[str, Any]]:
    s = get_settings()
    res = fetcher.get(f"{s.kosis_base_url}/statisticsData.do",
                      {"method": "getMeta", "type": "ITM", "apiKey": s.kosis_api_key, "orgId": s.kosis_org_id,
                       "tblId": s.kosis_tbl_id, "format": "json", "jsonVD": "Y"}, source="KOSIS_META")
    return _json(res)


def fetch_sido(fetcher: Fetcher, sido: str, age_codes: list[str], period: str) -> list[dict[str, Any]]:
    s = get_settings()
    p: dict[str, Any] = {"method": "getList", "apiKey": s.kosis_api_key, "orgId": s.kosis_org_id,
                         "tblId": s.kosis_tbl_id, "objL1": f"{sido}*", "objL2": "+".join(age_codes),
                         "itmId": "T2", "prdSe": "M", "format": "json", "jsonVD": "Y"}
    if period == "latest":
        p["newEstPrdCnt"] = "1"
    else:
        p["startPrdDe"] = p["endPrdDe"] = period
    return _json(fetcher.get(f"{s.kosis_base_url}/Param/statisticsParameterData.do", p, source="KOSIS_POP"))


def _int(v: Any) -> int | None:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def aggregate(rows: list[dict[str, Any]], total_code: str, aged: list[str]) -> dict[str, dict[str, Any]]:
    """[{C1, C2, DT, PRD_DE}] → {지역코드: {tot, aged65, period, name}}"""
    out: dict[str, dict[str, Any]] = {}
    aged_set = set(aged)
    for r in rows:
        cd, age, v = str(r.get("C1")), str(r.get("C2")), _int(r.get("DT"))
        d = out.setdefault(cd, {"tot": None, "aged65": 0, "aged_n": 0, "period": r.get("PRD_DE"), "name": r.get("C1_NM")})
        if age == total_code:
            d["tot"] = v
        elif age in aged_set and v is not None:
            d["aged65"] += v
            d["aged_n"] += 1
    for d in out.values():  # 65+ 구간이 하나도 안 왔으면 모름
        if d["aged_n"] == 0:
            d["aged65"] = None
    return out


_UPSERT = text("""
    INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn, aged65_ratio,
                                        kosis_cd, kosis_nm, match_method, collect_run_id, loaded_at)
    VALUES (:adm_cd, :y, :period, :tot, :aged, :ratio, :kcd, :knm, :method, :run, now())
    ON CONFLICT (adm_cd, stat_year) DO UPDATE SET ref_period = EXCLUDED.ref_period, tot_ppltn = EXCLUDED.tot_ppltn,
        aged65_ppltn = EXCLUDED.aged65_ppltn, aged65_ratio = EXCLUDED.aged65_ratio, kosis_cd = EXCLUDED.kosis_cd,
        kosis_nm = EXCLUDED.kosis_nm, match_method = EXCLUDED.match_method,
        collect_run_id = EXCLUDED.collect_run_id, loaded_at = now()""")


def collect_kosis(year: int | None = None) -> uuid.UUID | None:
    s = get_settings()
    if not s.kosis_api_key:
        log.warning("KOSIS_API_KEY 없음 — KOSIS 적재를 건너뜁니다")
        return None
    year = year or s.stat_year
    period = s.kosis_period_resolved
    run_id = runs.start_run(KIND, scope=f"{s.kosis_org_id}/{s.kosis_tbl_id};period={period};year={year}")
    fetcher = Fetcher(run_id, "KOSIS_POP", secrets=[s.kosis_api_key])
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"rows": 0, "failedCodes": [], "doneCodes": [], "period": period, "year": year}
    t0 = time.monotonic()
    try:
        meta = fetch_meta(fetcher)
        meta_regions = {m["ITM_ID"]: m["ITM_NM"] for m in meta if m.get("OBJ_ID") == "A"}
        total_code, aged = aged_codes([(m["ITM_ID"], m["ITM_NM"]) for m in meta if m.get("OBJ_ID") == "B"])
        if not total_code or not aged:
            raise KosisError("META", "연령 분류(계·65세 이상)를 찾지 못했습니다.")
        kosis_sidos = {c: n for c, n in meta_regions.items() if len(c) == 2 and c != "00"}

        values: dict[str, dict[str, Any]] = {}
        for sido in sorted(kosis_sidos):
            try:
                rows = fetch_sido(fetcher, sido, [total_code, *aged], period)
                values.update(aggregate(rows, total_code, aged))
                stats["doneCodes"].append(sido)
            except KosisError as e:
                if e.code == "30":  # 조회결과 없음 — 그 시점에 없던(폐지·신설) 시도
                    continue
                stats["failedCodes"].append(sido)
                with begin() as c:
                    dq.add(c, "FETCH_FAILED", "mart.area_resident_pop", sido, {"error": str(e)})
            time.sleep(0.35)  # 분당 200건 제한 안쪽

        # 계층은 '그 시점 자료'의 코드·이름으로 만듦 (예: 화성시는 2026년 구 신설 전후로 코드가 다름)
        names = {cd: v.get("name") or meta_regions.get(cd, cd) for cd, v in values.items()}
        tree = KosisTree.build([(cd, names[cd], infer_parent(cd, names)) for cd in values])
        with begin() as c:
            sido_names = dict(c.execute(text("""SELECT adm_cd, adm_nm FROM mart.area_population
                                                WHERE stat_year = :y AND length(adm_cd) = 2"""), {"y": year}).all())
            sgis = [SgisArea(*r) for r in c.execute(text("""SELECT adm_cd, adm_nm, level, parent_cd FROM mart.admin_area
                                                           WHERE stat_year = :y AND level IN (2, 3)"""), {"y": year})]
            pairs = match(tree, sido_names, sgis, kosis_sidos, available=set(values))
            c.execute(text("DELETE FROM mart.area_resident_pop WHERE stat_year = :y"), {"y": year})
            for adm_cd, (kcd, method) in pairs.items():
                v = values[kcd]
                ratio = round(100.0 * v["aged65"] / v["tot"], 2) if v["tot"] and v["aged65"] is not None else None
                c.execute(_UPSERT, {"adm_cd": adm_cd, "y": year, "period": v["period"] or period, "tot": v["tot"],
                                    "aged": v["aged65"], "ratio": ratio, "kcd": kcd, "knm": tree.regions[kcd].name,
                                    "method": method, "run": run_id})
            # 시군구 이름이 안 맞았지만 하위 읍면동이 맞은 경우 → 하위 합
            c.execute(text("""
                INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn, aged65_ratio,
                                                    match_method, collect_run_id)
                SELECT a.adm_cd, :y, max(r.ref_period), sum(r.tot_ppltn), sum(r.aged65_ppltn),
                       round(100.0 * sum(r.aged65_ppltn) / nullif(sum(r.tot_ppltn), 0), 2), 'CHILD_SUM', :run
                  FROM mart.admin_area a
                  JOIN mart.admin_area ch ON ch.stat_year = a.stat_year AND ch.level = 3 AND ch.parent_cd = a.adm_cd
                  JOIN mart.area_resident_pop r ON r.adm_cd = ch.adm_cd AND r.stat_year = a.stat_year
                 WHERE a.stat_year = :y AND a.level = 2
                   AND NOT EXISTS (SELECT 1 FROM mart.area_resident_pop x WHERE x.adm_cd = a.adm_cd AND x.stat_year = :y)
                 GROUP BY a.adm_cd"""), {"y": year, "run": run_id})
            dq.add_sql(c, "KOSIS_UNMATCHED", "mart.admin_area", """
                SELECT a.adm_cd, jsonb_build_object('admNm', a.adm_nm, 'level', a.level)
                  FROM mart.admin_area a
                  LEFT JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = a.stat_year
                 WHERE a.stat_year = :y AND a.level IN (2, 3) AND r.adm_cd IS NULL""", {"y": year})
            stats["dq"] = dq.record_checks(c, ("KOSIS_UNMATCHED", "FETCH_FAILED"))
            counts = dict(c.execute(text("""SELECT match_method, count(*) FROM mart.area_resident_pop
                                            WHERE stat_year = :y GROUP BY 1"""), {"y": year}).all())
            n_sgis = len(sgis)
        stats.update({"rows": sum(counts.values()), "matched": counts, "sgisAreas": n_sgis,
                      "kosisRegionsWithData": len(values), "calls": fetcher.calls, "errors": fetcher.errors,
                      "refPeriods": sorted({v["period"] for v in values.values() if v.get("period")}),
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "DONE" if not stats["failedCodes"] else ("PARTIAL" if stats["doneCodes"] else "FAILED")
        runs.finish_run(run_id, status, stats)
        log.info("kosis done", extra={"runId": str(run_id), "matched": counts, "sgisAreas": n_sgis})
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
