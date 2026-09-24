"""① SGIS 집계구(통계 최소 단위, 평균 약 500명) 인구·경계 적재.

- 인구: 총조사 주요지표를 시군구마다 low_search=2 로 부르면 그 시군구의 모든 집계구가 옵니다(252회).
- 경계: 집계구 경계 API 는 읍면동 단위로만 받을 수 있어 읍면동마다 1회(약 3,600회, 15분 안팎).
  이미 경계가 있는 읍면동은 건너뛰므로 중간에 끊겨도 다시 실행하면 이어서 받습니다(--refresh 로 전부 다시).
원문은 크기와 관계없이 gzip 으로 보관합니다(경계 원문만 수백 MB 가 되는 것을 방지).
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
from atlas.collector.sgis.client import SgisClient, SgisError
from atlas.collector.sgis.pipeline import detect_srid, parse_population
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)

_UPSERT_POP = text("""
    INSERT INTO mart.oa_area (oa_cd, stat_year, emd_cd, tot_ppltn, pop_run_id, loaded_at)
    VALUES (:oa_cd, :y, :emd, :pop, :run, now())
    ON CONFLICT (oa_cd, stat_year) DO UPDATE SET tot_ppltn = EXCLUDED.tot_ppltn, emd_cd = EXCLUDED.emd_cd,
        pop_run_id = EXCLUDED.pop_run_id, loaded_at = now()""")

_UPSERT_GEOM = text("""
    WITH g AS (
        SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
                   ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:gj), CAST(:srid AS int)), 5179)), 3)) AS g
    )
    INSERT INTO mart.oa_area (oa_cd, stat_year, emd_cd, geom_5179, rep_point_5179, bnd_run_id, loaded_at)
    SELECT :oa_cd, :y, :emd, ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(g, 5)), 3)),
           ST_PointOnSurface(g), :run, now()
      FROM g WHERE NOT ST_IsEmpty(g)
    ON CONFLICT (oa_cd, stat_year) DO UPDATE SET geom_5179 = EXCLUDED.geom_5179,
        rep_point_5179 = EXCLUDED.rep_point_5179, bnd_run_id = EXCLUDED.bnd_run_id, loaded_at = now()""")


def collect_oa(year: int | None = None, refresh: bool = False, pop: bool = True, bnd: bool = True) -> uuid.UUID:
    s = get_settings()
    year = year or s.stat_year
    run_id = runs.start_run("SGIS_OA", scope=f"year={year};refresh={refresh}")
    fetcher = Fetcher(run_id, "SGIS_OA_POP", secrets=[s.sgis_consumer_key, s.sgis_consumer_secret], gzip_threshold=0)
    sgis = SgisClient(fetcher)
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"popRows": 0, "geomRows": 0, "failedCodes": [], "doneCodes": [], "skipped": 0}
    t0 = time.monotonic()
    try:
        with begin() as c:
            sggs = [r[0] for r in c.execute(text(
                "SELECT adm_cd FROM mart.admin_area WHERE stat_year = :y AND level = 2 ORDER BY adm_cd"), {"y": year})]
            emds = [r[0] for r in c.execute(text(
                "SELECT adm_cd FROM mart.admin_area WHERE stat_year = :y AND level = 3 ORDER BY adm_cd"), {"y": year})]
            have = set() if refresh else {r[0] for r in c.execute(text(
                "SELECT DISTINCT emd_cd FROM mart.oa_area WHERE stat_year = :y AND geom_5179 IS NOT NULL"), {"y": year})}
            have_pop = set() if refresh else {r[0] for r in c.execute(text(
                "SELECT DISTINCT left(emd_cd, 5) FROM mart.oa_area WHERE stat_year = :y AND tot_ppltn IS NOT NULL"), {"y": year})}
        if not sggs:
            raise RuntimeError(f"{year}년 행정구역이 없습니다. 먼저 `make sgis` 를 실행하세요.")

        if pop:
            for i, sgg in enumerate(sggs):
                if sgg in have_pop:
                    stats["skipped"] += 1
                    continue
                try:
                    rows = [r for r in parse_population(sgis.get("stats/population.json",
                            {"year": year, "adm_cd": sgg, "low_search": 2}, "SGIS_OA_POP")) if len(r["adm_cd"]) >= 12]
                    with begin() as c:
                        if rows:
                            c.execute(_UPSERT_POP, [{"oa_cd": r["adm_cd"], "y": year, "emd": r["adm_cd"][:8],
                                                     "pop": r["tot_ppltn"], "run": run_id} for r in rows])
                    stats["popRows"] += len(rows)
                except SgisError as e:
                    stats["failedCodes"].append(f"pop:{sgg}")
                    with begin() as c:
                        dq.add(c, "FETCH_FAILED", "mart.oa_area", sgg, {"part": "pop", "error": str(e)})
                if i % 25 == 0:
                    log.info("oa pop progress", extra={"at": sgg, "rows": stats["popRows"]})

        if bnd:
            for i, emd in enumerate(emds):
                if emd in have:
                    stats["skipped"] += 1
                    continue
                try:
                    feats = sgis.get("boundary/statsarea.geojson", {"year": year, "adm_cd": emd}, "SGIS_OA_BND").get("features") or []
                    with begin() as c:
                        for f in feats:
                            cd = str((f.get("properties") or {}).get("adm_cd") or "")
                            if len(cd) < 12 or not f.get("geometry"):
                                continue
                            c.execute(_UPSERT_GEOM, {"gj": json.dumps(f["geometry"]), "srid": detect_srid(f["geometry"]),
                                                     "oa_cd": cd, "y": year, "emd": cd[:8], "run": run_id})
                            stats["geomRows"] += 1
                    stats["doneCodes"].append(emd)
                except SgisError as e:
                    if str(e.code) == "-100":   # 검색결과 없음 — 경계가 없는 신설 행정동 등. 실패가 아니라 빈 자료
                        stats.setdefault("noData", []).append(emd)
                        continue
                    stats["failedCodes"].append(f"bnd:{emd}")
                    with begin() as c:
                        dq.add(c, "FETCH_FAILED", "mart.oa_area", emd, {"part": "bnd", "error": str(e)})
                if i % 100 == 0:
                    log.info("oa boundary progress", extra={"at": emd, "i": i, "of": len(emds), "rows": stats["geomRows"]})
                    runs.save_stats(run_id, {**stats, "doneCodes": len(stats["doneCodes"])})

        with begin() as c:
            dq.add_sql(c, "OA_UNMATCHED", "mart.oa_area", """
                SELECT oa_cd, jsonb_build_object('emdCd', emd_cd,
                       'missing', CASE WHEN geom_5179 IS NULL THEN 'geom' ELSE 'pop' END)
                  FROM mart.oa_area WHERE stat_year = :y AND (geom_5179 IS NULL OR tot_ppltn IS NULL)""", {"y": year})
            stats["dq"] = dq.record_checks(c, ("OA_UNMATCHED", "FETCH_FAILED"))
            stats["oaTotal"], stats["oaReady"], stats["oaPpltn"] = c.execute(text("""
                SELECT count(*), count(*) FILTER (WHERE geom_5179 IS NOT NULL AND tot_ppltn IS NOT NULL),
                       sum(tot_ppltn) FILTER (WHERE geom_5179 IS NOT NULL) FROM mart.oa_area WHERE stat_year = :y"""),
                {"y": year}).one()
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "doneCodes": len(stats["doneCodes"]),
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        runs.finish_run(run_id, "DONE" if not stats["failedCodes"] else "PARTIAL", stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        stats["doneCodes"] = len(stats["doneCodes"]) if isinstance(stats["doneCodes"], list) else stats["doneCodes"]
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
