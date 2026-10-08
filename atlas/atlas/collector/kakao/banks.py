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

from atlas.ops import runs
from atlas.collector.kakao.client import KakaoStop, bank_brand, call, classify_bank, make_fetcher
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)
RADIUS_M = 20000

_UPSERT = text("""
    INSERT INTO mart.bank_place (place_id, name, category, brand, kind, addr, geom, geom_5179, collect_run_id)
    VALUES (:id, :name, :cat, :brand, :kind, :addr, ST_SetSRID(ST_MakePoint(:x, :y), 4326),
            ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 5179), :run)
    ON CONFLICT (place_id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category, brand = EXCLUDED.brand,
        kind = EXCLUDED.kind, addr = EXCLUDED.addr, geom = EXCLUDED.geom, geom_5179 = EXCLUDED.geom_5179,
        last_seen = now(), collect_run_id = EXCLUDED.collect_run_id""")


def _row(d: dict[str, Any], kind: str, run_id: uuid.UUID) -> dict[str, Any]:
    return {"id": d["id"], "name": d.get("place_name"), "cat": d.get("category_name"),
            "brand": bank_brand(d.get("category_name")), "kind": kind,
            "addr": d.get("road_address_name") or d.get("address_name"),
            "x": float(d["x"]), "y": float(d["y"]), "run": run_id}


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
                        rows.append(_row(d, kind, run_id))
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


# ── 전수 수집 (사분할 격자) ─────────────────────────────────────────────────────────────────────
# 대표점마다 '가까운 3곳' 방식은 지역 최근접에는 정확하지만 도시의 지점을 많이 놓침(은행 지점 영향평가에는 부족).
# 카카오 범주 검색은 한 요청에 최대 45곳(15 × 3쪽)만 주므로, 사각형(rect) 안의 total_count 가 45를 넘으면
# 네 칸으로 나눠 다시 묻습니다. 바다·산 등 빈 칸은 1회로 끝나 호출 수는 지점 밀도에 비례합니다.
KOREA_BBOX = (124.5, 33.0, 131.0, 38.7)    # 울릉도 포함 (독도에는 지점 없음)
START_STEP = 0.5                          # 시작 격자(도)
MIN_SIDE = 0.002                          # 약 200m — 더 나누지 않고 45곳까지만 (잘림으로 기록)
PAGE_MAX = 45


def _tiles(bbox: tuple[float, float, float, float], step: float) -> list[tuple[float, float, float, float]]:
    x1, y1, x2, y2 = bbox
    out = []
    y = y1
    while y < y2:
        x = x1
        while x < x2:
            out.append((round(x, 6), round(y, 6), round(min(x + step, x2), 6), round(min(y + step, y2), 6)))
            x += step
        y += step
    return out


def split4(t: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    x1, y1, x2, y2 = t
    mx, my = round((x1 + x2) / 2, 6), round((y1 + y2) / 2, 6)
    return [(x1, y1, mx, my), (mx, y1, x2, my), (x1, my, mx, y2), (mx, my, x2, y2)]


def collect_banks_full() -> uuid.UUID:
    """전국 은행·금고 지점 전수 수집. scope 가 'FULL' 로 시작하는 마지막 DONE 실행이 지표 계산의 기준 목록이 됨
    (그 실행에서 보이지 않은 지점은 폐점 가능성이 있어 계산에서 뺌 — calc/07_bank.sql)."""
    s = get_settings()
    run_id = runs.start_run("KAKAO_BANK", scope=f"FULL;BK9;quadtree;start={START_STEP};min={MIN_SIDE}")
    fetcher = make_fetcher(run_id, "KAKAO_LOCAL")
    stats: dict[str, Any] = {"tiles": 0, "splits": 0, "truncated": 0, "emptyTiles": 0, "failedTiles": 0,
                             "failedPages": 0, "branches": 0, "atms": 0, "skipped": 0, "stoppedBy": None}
    t0 = time.monotonic()
    seen: set[str] = set()
    stack = _tiles(KOREA_BBOX, START_STEP)
    url = f"{s.kakao_local_base}/v2/local/search/category.json"

    def page(tile: tuple[float, float, float, float], n: int) -> dict[str, Any] | None:
        return call(fetcher, url, {"category_group_code": "BK9", "rect": ",".join(f"{v:.6f}" for v in tile),
                                   "size": 15, "page": n}, "KAKAO_LOCAL")

    def save(docs: list[dict[str, Any]]) -> None:
        rows = []
        for d in docs:
            kind = classify_bank(d.get("place_name", ""), d.get("category_name", ""))
            if kind is None:
                stats["skipped"] += 1
                continue
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            rows.append(_row(d, kind, run_id))
            stats["branches" if kind == "BRANCH" else "atms"] += 1
        if rows:
            with begin() as c:
                c.execute(_UPSERT, rows)

    try:
        while stack:
            tile = stack.pop()
            stats["tiles"] += 1
            try:
                first = page(tile, 1)
                if first is None:
                    stats["failedTiles"] += 1
                    continue
                total = int((first.get("meta") or {}).get("total_count") or 0)
                if total == 0:
                    stats["emptyTiles"] += 1
                    continue
                if total > PAGE_MAX and (tile[2] - tile[0]) > MIN_SIDE:
                    stats["splits"] += 1
                    stack.extend(split4(tile))
                    continue
                if total > PAGE_MAX:
                    stats["truncated"] += 1
                save(first.get("documents") or [])
                for n in range(2, min(3, -(-total // 15)) + 1):
                    nxt = page(tile, n)
                    if nxt is None:                 # 재시도 끝에 실패 — 이 칸의 나머지 지점을 못 받음
                        stats["failedPages"] += 1
                        break
                    save(nxt.get("documents") or [])
            except KakaoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                stats["remainingTiles"] = len(stack) + 1
                break
            if stats["tiles"] % 500 == 0:
                log.info("bank full progress", extra={"tiles": stats["tiles"], "queued": len(stack), "places": len(seen)})
        with begin() as c:
            stats["totalBranches"] = c.execute(text("SELECT count(*) FROM mart.bank_place WHERE kind = 'BRANCH'")).scalar_one()
            stats["unseenBranches"] = c.execute(text("""SELECT count(*) FROM mart.bank_place
                WHERE kind = 'BRANCH' AND last_seen < (SELECT started_at FROM ops.collect_run WHERE collect_run_id = :r)"""),
                {"r": run_id}).scalar_one()
        stats.update({"places": len(seen), "calls": fetcher.calls, "errors": fetcher.errors,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        # 받지 못한 칸·쪽이 있거나 45곳에서 잘린 칸이 있으면 '전수'라고 할 수 없으므로 PARTIAL
        # — 전수(DONE) 실행은 기준 목록이 되어 그 실행에서 안 보인 지점을 폐점으로 빼므로, 빠짐이 있으면 안 됨.
        # 계산은 이전 전수 실행(또는 90일 규칙)을 계속 씀
        ok = not (stats["stoppedBy"] or stats["failedTiles"] or stats["failedPages"] or stats["truncated"])
        runs.finish_run(run_id, "DONE" if ok else "PARTIAL", stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id
