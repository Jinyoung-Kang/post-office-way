"""④ 은행·금고 지점 수집 — 카카오 로컬 범주 검색(BK9, 은행)을 지역 대표점마다 거리순으로 호출.

지역 대표점마다 가장 가까운 지점을 최소 3곳(최대 3페이지·45곳) 찾을 때까지 받으므로, 모든 지역의
'최근접 지점'은 반드시 합집합에 들어갑니다(20km 안이라면). ATM·우체국365 는 kind 로 나눠 저장하고
금융 공백 지표는 대면 창구(BRANCH)만 씁니다. 약 3,800회 × 1~3페이지 호출.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.kakao.client import KakaoStop, call, classify_bank, make_fetcher
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)
RADIUS_M = 20000

_UPSERT = text("""
    INSERT INTO mart.bank_place (place_id, name, category, kind, addr, geom, geom_5179, collect_run_id)
    VALUES (:id, :name, :cat, :kind, :addr, ST_SetSRID(ST_MakePoint(:x, :y), 4326),
            ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 5179), :run)
    ON CONFLICT (place_id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category, kind = EXCLUDED.kind,
        addr = EXCLUDED.addr, geom = EXCLUDED.geom, geom_5179 = EXCLUDED.geom_5179, last_seen = now(),
        collect_run_id = EXCLUDED.collect_run_id""")


def collect_banks(year: int | None = None, min_branches: int = 3) -> uuid.UUID:
    s = get_settings()
    year = year or s.stat_year
    run_id = runs.start_run("KAKAO_BANK", scope=f"BK9;radius={RADIUS_M};year={year}")
    fetcher = make_fetcher(run_id, "KAKAO_LOCAL")
    stats: dict[str, Any] = {"points": 0, "places": 0, "branches": 0, "atms": 0, "skippedPost": 0, "stoppedBy": None}
    t0 = time.monotonic()
    seen: set[str] = set()
    try:
        with begin() as c:
            pts = c.execute(text("""SELECT adm_cd, ST_X(rep_point), ST_Y(rep_point) FROM mart.admin_area
                                    WHERE stat_year = :y ORDER BY level DESC, adm_cd"""), {"y": year}).all()
        if not pts:
            raise RuntimeError(f"{year}년 행정구역이 없습니다. 먼저 `make sgis` 를 실행하세요.")
        for i, (_cd, x, y) in enumerate(pts):
            found = 0
            try:
                for page in (1, 2, 3):
                    data = call(fetcher, f"{s.kakao_local_base}/v2/local/search/category.json",
                                {"category_group_code": "BK9", "x": f"{x:.6f}", "y": f"{y:.6f}", "radius": RADIUS_M,
                                 "sort": "distance", "size": 15, "page": page}, "KAKAO_LOCAL")
                    if not data:
                        break
                    rows = []
                    for d in data.get("documents") or []:
                        kind = classify_bank(d.get("place_name", ""), d.get("category_name", ""))
                        if kind is None:
                            stats["skippedPost"] += 1
                            continue
                        found += kind == "BRANCH"
                        if d["id"] in seen:
                            continue
                        seen.add(d["id"])
                        rows.append({"id": d["id"], "name": d.get("place_name"), "cat": d.get("category_name"),
                                     "kind": kind, "addr": d.get("road_address_name") or d.get("address_name"),
                                     "x": float(d["x"]), "y": float(d["y"]), "run": run_id})
                        stats["branches" if kind == "BRANCH" else "atms"] += 1
                    if rows:
                        with begin() as c:
                            c.execute(_UPSERT, rows)
                    if found >= min_branches or (data.get("meta") or {}).get("is_end", True):
                        break
            except KakaoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
            stats["points"] += 1
            if i % 200 == 0:
                log.info("bank progress", extra={"i": i, "of": len(pts), "places": len(seen)})
        stats["places"] = len(seen)
        with begin() as c:
            stats["totalBranches"] = c.execute(text("SELECT count(*) FROM mart.bank_place WHERE kind = 'BRANCH'")).scalar_one()
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "elapsedMs": int((time.monotonic() - t0) * 1000)})
        runs.finish_run(run_id, "PARTIAL" if stats["stoppedBy"] else "DONE", stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
