"""SGIS 인구 주요지표·행정구역 경계 적재 (FR-202~204).

호출 수 = 시도 수 × (인구 + 경계) × 레벨 수 수준 — 일 50,000회 한도와 거리가 멉니다(NFR-08).
경계는 좌표값 크기로 좌표계를 판정해(ADR-002) EPSG:4326·5179 두 벌로 저장하고,
대표점은 ST_PointOnSurface 로 폴리곤 안에 둡니다.
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
from atlas.core.config import get_settings
from atlas.core.db import begin

log = logging.getLogger(__name__)

# SGIS 시도 코드 (인구 API 로 목록을 못 받을 때의 대체값)
SIDO_FALLBACK = {
    "11": "서울특별시", "21": "부산광역시", "22": "대구광역시", "23": "인천광역시", "24": "광주광역시",
    "25": "대전광역시", "26": "울산광역시", "29": "세종특별자치시", "31": "경기도", "32": "강원특별자치도",
    "33": "충청북도", "34": "충청남도", "35": "전북특별자치도", "36": "전라남도", "37": "경상북도",
    "38": "경상남도", "39": "제주특별자치도",
}
SIMPLIFY_TOL_M = {2: 200.0, 3: 50.0}

# 경계 API 이름은 "서울특별시 종로구" 같은 전체 이름 → 인구 API 의 짧은 이름("종로구")으로 맞춤
_SHORT_NAMES = text("""UPDATE mart.admin_area a SET adm_nm = p.adm_nm FROM mart.area_population p
                       WHERE p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year AND a.stat_year = :y
                         AND coalesce(p.adm_nm, '') <> '' AND a.adm_nm <> p.adm_nm""")


def _num(v: Any) -> float | None:
    if v in (None, "", "N/A", "null"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def detect_srid(geometry: dict[str, Any]) -> int:
    """첫 좌표가 경위도 범위면 4326, 수십만~백만 단위면 UTM-K(5179)."""
    c: Any = geometry.get("coordinates")
    while isinstance(c, list) and c and isinstance(c[0], list):
        c = c[0]
    if not c:
        return 5179
    x, y = float(c[0]), float(c[1])
    return 4326 if abs(x) <= 180 and abs(y) <= 90 else 5179


def parse_population(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("result") or []:
        cd = str(r.get("adm_cd") or "").strip()
        if not cd:
            continue
        tp = _num(r.get("tot_ppltn"))
        out.append({"adm_cd": cd, "adm_nm": (r.get("adm_nm") or "").strip(),
                    "tot_ppltn": int(tp) if tp is not None else None,
                    "ppltn_dnsty": _num(r.get("ppltn_dnsty")),
                    "aged_child_idx": _num(r.get("aged_child_idx")),
                    "avg_age": _num(r.get("avg_age"))})
    return out


def _sido_list(sgis: SgisClient, year: int) -> dict[str, str]:
    try:
        rows = parse_population(sgis.get("stats/population.json", {"year": year, "low_search": 1}, "SGIS_POP"))
        got = {r["adm_cd"]: r["adm_nm"] for r in rows if len(r["adm_cd"]) == 2}
        if got:
            return got
    except SgisError as e:
        log.warning("sido list fallback", extra={"error": str(e)})
    return dict(SIDO_FALLBACK)


def _target_sido(all_sido: dict[str, str]) -> dict[str, str]:
    want = get_settings().sgis_sido.strip().lower()
    if want in ("", "all"):
        return all_sido
    codes = [x.strip() for x in want.split(",") if x.strip()]
    return {c: all_sido.get(c, SIDO_FALLBACK.get(c, c)) for c in codes}


_UPSERT_POP = text("""
    INSERT INTO mart.area_population (adm_cd, stat_year, adm_nm, tot_ppltn, ppltn_dnsty, aged_child_idx,
                                      avg_age, collect_run_id, loaded_at)
    VALUES (:adm_cd, :year, :adm_nm, :tot_ppltn, :ppltn_dnsty, :aged_child_idx, :avg_age, :run, now())
    ON CONFLICT (adm_cd, stat_year) DO UPDATE SET adm_nm = EXCLUDED.adm_nm, tot_ppltn = EXCLUDED.tot_ppltn,
        ppltn_dnsty = EXCLUDED.ppltn_dnsty, aged_child_idx = EXCLUDED.aged_child_idx,
        avg_age = EXCLUDED.avg_age, collect_run_id = EXCLUDED.collect_run_id, loaded_at = now()""")


def collect_population(year: int | None = None, levels: list[int] | None = None) -> uuid.UUID:
    s = get_settings()
    year, levels = year or s.stat_year, levels or s.levels
    run_id = runs.start_run("SGIS_POP", scope=f"sido={s.sgis_sido};levels={levels};year={year}")
    fetcher = Fetcher(run_id, "SGIS_POP", secrets=[s.sgis_consumer_key, s.sgis_consumer_secret])
    sgis = SgisClient(fetcher)
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"rows": 0, "failedCodes": [], "doneCodes": [], "year": year}
    t0 = time.monotonic()
    try:
        sidos = _target_sido(_sido_list(sgis, year))
        with begin() as c:  # 시도(level 1) 이름·인구도 같이 저장 — 화면의 시도 선택용
            for cd, nm in sidos.items():
                c.execute(_UPSERT_POP, {"adm_cd": cd, "year": year, "adm_nm": nm, "tot_ppltn": None,
                                        "ppltn_dnsty": None, "aged_child_idx": None, "avg_age": None, "run": run_id})
        for sido in sidos:
            for lvl in [l for l in levels if l in (2, 3)]:
                try:
                    data = sgis.get("stats/population.json",
                                    {"year": year, "adm_cd": sido, "low_search": lvl - 1}, "SGIS_POP")
                    rows = parse_population(data)
                    with begin() as c:
                        for r in rows:
                            c.execute(_UPSERT_POP, {**r, "year": year, "run": run_id})
                    stats["rows"] += len(rows)
                    stats["doneCodes"].append(f"{sido}:L{lvl}")
                except SgisError as e:
                    stats["failedCodes"].append(f"{sido}:L{lvl}")
                    with begin() as c:
                        dq.add(c, "FETCH_FAILED", "mart.area_population", sido,
                               {"level": lvl, "error": str(e)})
        # 시도 합계는 하위 시군구 합으로 채움(주요지표 시도 호출을 아끼기 위함)
        with begin() as c:
            c.execute(text("""UPDATE mart.area_population p SET tot_ppltn = q.s
                              FROM (SELECT left(adm_cd, 2) sido, sum(tot_ppltn) s FROM mart.area_population
                                    WHERE stat_year = :y AND length(adm_cd) = 5 GROUP BY 1) q
                              WHERE p.stat_year = :y AND p.adm_cd = q.sido"""), {"y": year})
            c.execute(_SHORT_NAMES, {"y": year})
            _pop_dq(c, dq, run_id, year)
            stats["dq"] = dq.record_checks(c, ("POP_NULL", "FETCH_FAILED"))
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "tokens": sgis.token_issued,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "DONE" if not stats["failedCodes"] else ("PARTIAL" if stats["doneCodes"] else "FAILED")
        runs.finish_run(run_id, status, stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id


def _pop_dq(c, dq: DQRecorder, run_id: uuid.UUID, year: int) -> None:
    dq.add_sql(c, "POP_NULL", "mart.area_population", """
        SELECT adm_cd AS target_key, jsonb_build_object('admNm', adm_nm, 'totPpltn', tot_ppltn,
               'agedChildIdx', aged_child_idx) AS detail
        FROM mart.area_population WHERE collect_run_id = :run AND stat_year = :y AND length(adm_cd) > 2
          AND (tot_ppltn IS NULL OR aged_child_idx IS NULL)""", {"run": run_id, "y": year})


_UPSERT_AREA = text("""
    WITH src AS (
        SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
                   ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:gj), CAST(:srid AS int)), 5179)), 3)) AS g5179
    ), g AS (
        SELECT g5179, ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(g5179, 4326)), 3)) AS g4326 FROM src
    )
    INSERT INTO mart.admin_area (adm_cd, stat_year, adm_nm, level, parent_cd, geom, geom_5179, geom_simple,
                                 rep_point, rep_point_5179, src_crs, collect_run_id, loaded_at)
    SELECT :adm_cd, :year, :adm_nm, :level, :parent, g4326, g5179,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(
               ST_Transform(ST_SimplifyPreserveTopology(g5179, CAST(:tol AS float8)), 4326)), 3)),
           ST_PointOnSurface(g4326), ST_Transform(ST_PointOnSurface(g4326), 5179),
           'EPSG:' || :srid, :run, now()
    FROM g WHERE NOT ST_IsEmpty(g4326)
    ON CONFLICT (adm_cd, stat_year) DO UPDATE SET adm_nm = EXCLUDED.adm_nm, level = EXCLUDED.level,
        parent_cd = EXCLUDED.parent_cd, geom = EXCLUDED.geom, geom_5179 = EXCLUDED.geom_5179,
        geom_simple = EXCLUDED.geom_simple, rep_point = EXCLUDED.rep_point,
        rep_point_5179 = EXCLUDED.rep_point_5179, src_crs = EXCLUDED.src_crs,
        collect_run_id = EXCLUDED.collect_run_id, loaded_at = now()""")


def load_features(c, features: list[dict[str, Any]], level: int, year: int, run_id: uuid.UUID) -> int:
    n = 0
    for f in features:
        props, geom = f.get("properties") or {}, f.get("geometry")
        cd = str(props.get("adm_cd") or props.get("ADM_CD") or "").strip()
        if not cd or not geom:
            continue
        parent = cd[:2] if level == 2 else cd[:5]
        # "서울특별시 종로구 청운효자동" → 상위 이름 떼기 (인구 API 짧은 이름이 있으면 나중에 그걸로 덮음)
        full = (props.get("adm_nm") or props.get("ADM_NM") or cd).strip()
        parts = full.split()
        short = " ".join(parts[level - 1:]) if len(parts) > level - 1 else full
        c.execute(_UPSERT_AREA, {"gj": json.dumps(geom), "srid": detect_srid(geom), "adm_cd": cd, "year": year,
                                 "adm_nm": short,
                                 "level": level, "parent": parent, "tol": SIMPLIFY_TOL_M[level], "run": run_id})
        n += 1
    return n


def _fetch_bnd(sgis: SgisClient, year: int, adm_cd: str, low: int) -> list[dict[str, Any]]:
    data = sgis.get("boundary/hadmarea.geojson", {"year": year, "adm_cd": adm_cd, "low_search": low}, "SGIS_BND")
    return data.get("features") or []


def collect_boundaries(year: int | None = None, levels: list[int] | None = None) -> uuid.UUID:
    s = get_settings()
    year, levels = year or s.stat_year, levels or s.levels
    run_id = runs.start_run("SGIS_BND", scope=f"sido={s.sgis_sido};levels={levels};year={year}")
    fetcher = Fetcher(run_id, "SGIS_BND", secrets=[s.sgis_consumer_key, s.sgis_consumer_secret])
    sgis = SgisClient(fetcher)
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"rows": 0, "failedCodes": [], "doneCodes": [], "year": year, "sourceYear": None}
    t0 = time.monotonic()
    try:
        sidos = _target_sido(_sido_list(sgis, year))
        src_year = None
        for sido in sidos:
            # 경계 연도가 아직 없으면 직전 연도로 대체(행정경계는 해마다 거의 같음) — stats.sourceYear 에 기록
            feats: list[dict[str, Any]] = []
            last_err: Exception | str = "빈 응답(features 0건)"
            for y in ([src_year] if src_year else [year, year - 1, year - 2]):
                try:
                    feats = _fetch_bnd(sgis, y, sido, 1)
                    if feats:
                        src_year = y
                        break
                except SgisError as e:
                    last_err = e
            if not feats:
                stats["failedCodes"].append(f"{sido}:L2")
                with begin() as c:
                    dq.add(c, "FETCH_FAILED", "mart.admin_area", sido, {"level": 2, "error": str(last_err)})
                continue
            level2_codes: list[str] = []
            with begin() as c:
                if 2 in levels:
                    stats["rows"] += load_features(c, feats, 2, year, run_id)
                level2_codes = [str((f.get("properties") or {}).get("adm_cd")) for f in feats]
            stats["doneCodes"].append(f"{sido}:L2")
            if 3 not in levels:
                continue
            try:
                f3 = _fetch_bnd(sgis, src_year, sido, 2)
            except SgisError:
                f3 = []
            if f3:
                with begin() as c:
                    stats["rows"] += load_features(c, f3, 3, year, run_id)
            else:  # 시도 → 2단계 아래 조회가 안 되면 시군구마다 한 단계 아래로
                for sgg in level2_codes:
                    try:
                        f3 = _fetch_bnd(sgis, src_year, sgg, 1)
                        with begin() as c:
                            stats["rows"] += load_features(c, f3, 3, year, run_id)
                    except SgisError as e:
                        stats["failedCodes"].append(f"{sgg}:L3")
                        with begin() as c:
                            dq.add(c, "FETCH_FAILED", "mart.admin_area", sgg, {"level": 3, "error": str(e)})
            stats["doneCodes"].append(f"{sido}:L3")
        stats["sourceYear"] = src_year
        with begin() as c:
            # 경계가 바뀌었으니 해당 연도 공간 매핑은 다음 계산에서 다시 만듭니다
            c.execute(text("DELETE FROM mart.facility_area_map WHERE stat_year = :y"), {"y": year})
            c.execute(_SHORT_NAMES, {"y": year})
            _bnd_dq(c, dq, run_id, year)
            stats["dq"] = dq.record_checks(c, ("GEOM_INVALID", "REP_POINT_OUTSIDE", "AREA_WITHOUT_POP", "FETCH_FAILED"))
        stats.update({"calls": fetcher.calls, "errors": fetcher.errors, "tokens": sgis.token_issued,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        status = "DONE" if not stats["failedCodes"] else ("PARTIAL" if stats["doneCodes"] else "FAILED")
        runs.finish_run(run_id, status, stats)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id


def _bnd_dq(c, dq: DQRecorder, run_id: uuid.UUID, year: int) -> None:
    p = {"run": run_id, "y": year}
    dq.add_sql(c, "GEOM_INVALID", "mart.admin_area", """
        SELECT adm_cd AS target_key, jsonb_build_object('admNm', adm_nm, 'reason', ST_IsValidReason(geom)) AS detail
        FROM mart.admin_area WHERE collect_run_id = :run AND stat_year = :y AND NOT ST_IsValid(geom)""", p)
    dq.add_sql(c, "REP_POINT_OUTSIDE", "mart.admin_area", """
        SELECT adm_cd, jsonb_build_object('admNm', adm_nm)
        FROM mart.admin_area WHERE collect_run_id = :run AND stat_year = :y AND NOT ST_Intersects(geom, rep_point)""", p)
    dq.add_sql(c, "AREA_WITHOUT_POP", "mart.admin_area", """
        SELECT a.adm_cd, jsonb_build_object('admNm', a.adm_nm, 'level', a.level)
        FROM mart.admin_area a LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
        WHERE a.collect_run_id = :run AND a.stat_year = :y AND p.adm_cd IS NULL""", p)


def collect_sgis(kind: str = "all") -> list[uuid.UUID]:
    out = []
    if kind in ("all", "pop"):
        out.append(collect_population())
    if kind in ("all", "bnd"):
        out.append(collect_boundaries())
    return out
