"""② 도보 계산 (작업 kind=walk, 지표 계산이 끝나면 자동으로 이어짐).

calc_run 하나에 대해
  1) 집계구 대표점·금융 우체국·은행 지점을 도보 그래프의 가장 가까운 꼭짓점에 붙이고(붙임 거리도 더함)
  2) 우체국 3곳·은행 2곳까지 k-최근접 탐색(ksource) → mart.oa_walk (COPY)
  3) 지역 지표(POPW_FIN_WALK_M · WALK30_*)와 은행 지점 영향평가의 도보 열을 SQL 로 채움
같은 calc_run 으로 다시 돌리면 그 calc_run 의 도보 결과를 지우고 새로 씀(멱등).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import numpy as np
from sqlalchemy import text

from atlas.core.config import get_settings
from atlas.core.db import get_engine
from atlas.core.jobctx import current_job_id
from atlas.core.masking import safe_error

log = logging.getLogger(__name__)
WALK_METRICS = ("POPW_FIN_WALK_M", "WALK30_NO_FIN_PPLTN", "WALK30_NO_FIN_SHARE", "WALK30_NO_CASH_PPLTN")
LAT0 = 36.5                                    # 한반도 중간 위도 — 꼭짓점 찾기용 평면 근사


def _xy(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    return np.column_stack([lon * 111_320.0 * np.cos(np.radians(LAT0)), lat * 110_574.0])


class Snapper:
    """점 → 가장 가까운 꼭짓점과 거리(m). KD-tree 는 평면 근사로 찾고 거리는 하버사인으로 다시 잼."""

    def __init__(self, lon: np.ndarray, lat: np.ndarray):
        from scipy.spatial import cKDTree

        self.lon, self.lat = lon, lat
        self.tree = cKDTree(_xy(lon, lat))

    def snap(self, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        from atlas.walk.graph import haversine

        if len(lon) == 0:
            return np.empty(0, dtype=np.int64), np.empty(0)
        _, idx = self.tree.query(_xy(lon, lat))
        return idx, haversine(lon, lat, self.lon[idx], self.lat[idx])


def nearest_k(g, snapper: Snapper, oa_lon, oa_lat, fac_lon, fac_lat, k: int, limit: float, snap_max: float
              ) -> tuple[np.ndarray, np.ndarray]:
    """집계구마다 걸어서 가까운 시설 k곳 → (시설 번호[n_oa, k] -1=없음, 거리[n_oa, k] inf=없음)."""
    from atlas.walk.ksource import k_nearest

    fv, fd = snapper.snap(fac_lon, fac_lat)
    seeds = [(float(d), int(v), i) for i, (v, d) in enumerate(zip(fv, fd)) if d <= snap_max]
    src, dist = k_nearest(g.indptr, g.indices, g.weights, seeds, k, limit)
    ov, od = snapper.snap(oa_lon, oa_lat)
    s, d = src[ov].copy(), dist[ov].astype(np.float64) + od[:, None]
    bad = (od > snap_max)[:, None] | (d > limit) | (s < 0)
    s[bad], d[bad] = -1, np.inf
    return s, d


def _copy_rows(c, rows: list[tuple]) -> None:
    """열린 트랜잭션(c) 안에서 COPY — 커밋은 호출한 쪽에서 (지우기·적재·지표를 한 번에)."""
    with c.connection.driver_connection.cursor() as cur, cur.copy(
            "COPY mart.oa_walk (calc_run_id, kind, oa_cd, rank, target, walk_m) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def run_walk(calc_run_id: str | None = None, graph=None) -> dict[str, Any]:
    from atlas.walk.graph import Graph
    from atlas.walk.osm import paths

    s = get_settings()
    eng = get_engine()
    if graph is None:
        gp = paths()["graph"]
        if not gp.exists():
            return {"skipped": "도보 그래프 없음 — `make osm` 으로 OSM 도로망을 먼저 받으세요."}
        graph = Graph.load(gp)
        from atlas.walk.osm import GRAPH_VERSION

        if (v := graph.meta.get("graphVersion")) != GRAPH_VERSION:   # 규칙이 바뀐 뒤 남은 예전 그래프는 쓰지 않음 (R12)
            return {"skipped": f"도보 그래프 규칙이 바뀌었습니다(파일 {v} ≠ 코드 {GRAPH_VERSION}) — `make osm` 으로 다시 만드세요."}
    with eng.connect() as c:
        run = c.execute(text("""SELECT calc_run_id, stat_year, facility_as_of, params FROM mart.calc_run
                                WHERE status = 'DONE' AND (CAST(:id AS uuid) IS NULL OR calc_run_id = CAST(:id AS uuid))
                                ORDER BY created_at DESC LIMIT 1"""), {"id": calc_run_id}).mappings().first()
    if not run:
        return {"skipped": "완료된 지표 계산이 없습니다."}
    rid, year = run["calc_run_id"], run["stat_year"]
    levels = [int(x) for x in run["params"]["levels"]]
    limit, snap_max = float(s.walk_limit_m), float(s.walk_snap_max_m)
    within = float(s.walk_speed_mps) * s.walk_minutes * 60          # 0.8m/s × 30분 = 1,440m
    t0 = time.monotonic()
    with eng.begin() as c:
        c.execute(text("""INSERT INTO mart.walk_run (calc_run_id, status, speed_mps, limit_m, graph, job_id)
                          VALUES (:r, 'RUNNING', :sp, :lim, CAST(:g AS jsonb), :j)
                          ON CONFLICT (calc_run_id) DO UPDATE SET status = 'RUNNING', speed_mps = EXCLUDED.speed_mps,
                              limit_m = EXCLUDED.limit_m, graph = EXCLUDED.graph, stats = '{}', error = NULL,
                              started_at = now(), finished_at = NULL, job_id = EXCLUDED.job_id"""),
                  {"r": rid, "sp": s.walk_speed_mps, "lim": limit, "g": json.dumps(graph.meta, ensure_ascii=False),
                   "j": current_job_id.get()})
    try:
        with eng.connect() as c:
            oa = c.execute(text("""
                SELECT n.oa_cd, ST_X(ST_Transform(o.rep_point_5179, 4326)) AS lon, ST_Y(ST_Transform(o.rep_point_5179, 4326)) AS lat
                  FROM mart.oa_nearest n JOIN mart.oa_area o ON o.oa_cd = n.oa_cd AND o.stat_year = :y
                 WHERE n.calc_run_id = :r ORDER BY n.oa_cd"""), {"r": rid, "y": year}).all()
            posts = c.execute(text("""
                SELECT CAST(hist_id AS text), ST_X(geom), ST_Y(geom) FROM mart.post_facility_hist
                 WHERE valid_from <= :a AND (valid_to IS NULL OR valid_to > :a) AND fin_available AND NOT is_center
                 ORDER BY hist_id"""), {"a": run["facility_as_of"]}).all()
            banks = c.execute(text("""
                SELECT b.place_id, ST_X(b.geom), ST_Y(b.geom) FROM mart.bank_branch_current b
                  JOIN mart.bank_brand bb ON bb.brand = b.brand AND bb.grp = 'BANK' ORDER BY b.place_id""")).all()
        if not oa:
            raise RuntimeError("집계구 최근접(oa_nearest)이 없습니다 — 집계구 수집(make oa) 뒤 지표를 다시 계산하세요.")
        snapper = Snapper(graph.lon, graph.lat)
        oa_lon = np.array([r[1] for r in oa])
        oa_lat = np.array([r[2] for r in oa])
        stats: dict[str, Any] = {"oa": len(oa), "posts": len(posts), "banks": len(banks)}
        rows: list[tuple] = []
        timings = {}
        for kind, fac, k in (("POST", posts, 3), ("BANK", banks, 2)):
            if not fac:
                continue
            t = time.monotonic()
            src, dist = nearest_k(graph, snapper, oa_lon, oa_lat, np.array([f[1] for f in fac]),
                                  np.array([f[2] for f in fac]), k, limit, snap_max)
            timings[kind] = int((time.monotonic() - t) * 1000)
            ids = [f[0] for f in fac]
            for i, (oa_cd, *_rest) in enumerate(oa):
                for j in range(k):
                    if src[i, j] >= 0:
                        rows.append((rid, kind, oa_cd, j + 1, ids[src[i, j]], round(float(dist[i, j]), 1)))
            stats[f"{kind.lower()}Reached"] = int((src[:, 0] >= 0).sum())
        stats["rows"] = len(rows)
        # 지우기·적재·지표 갱신을 한 트랜잭션으로 — 중간에 실패해도 화면은 이전 도보 결과를 그대로 씀.
        # 같은 계산 실행을 두 곳(make calc 의 walk·워커 연쇄)에서 동시에 돌리면 뒤의 것이 앞의 것을 기다림
        with eng.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('walk:' || CAST(:r AS text), 0))"), {"r": rid})
            c.execute(text("DELETE FROM mart.oa_walk WHERE calc_run_id = :r"), {"r": rid})
            _copy_rows(c, rows)
            # 방금 COPY 한 40만 행·계산이 넣은 지점 행이 통계에 없으면 아래 집계·UPDATE 가 나쁜 계획을 고름
            # (같은 트랜잭션 안에서 넣은 행도 ANALYZE 가 표본으로 셈)
            c.execute(text("ANALYZE mart.oa_walk"))
            c.execute(text("ANALYZE mart.bank_impact"))
            _metrics(c, rid, levels, limit, within)
            _bank_impact(c, rid, within)
            c.execute(text("""UPDATE mart.walk_run SET status = 'DONE', stats = CAST(:s AS jsonb), finished_at = now()
                              WHERE calc_run_id = :r"""),
                      {"r": rid, "s": json.dumps({**stats, "timingsMs": timings,
                                                  "elapsedMs": int((time.monotonic() - t0) * 1000)})})
        log.info("walk done", extra={"calcRunId": str(rid), **stats, "timingsMs": timings})
        return {"calcRunId": str(rid), **stats, "timingsMs": timings}
    except Exception as e:
        with eng.begin() as c:
            c.execute(text("""UPDATE mart.walk_run SET status = 'FAILED', error = :e, finished_at = now()
                              WHERE calc_run_id = :r"""), {"r": rid, "e": safe_error(f"{type(e).__name__}: {e}")})
        raise


def _metrics(c, rid: uuid.UUID, levels: list[int], limit: float, within: float) -> None:
    """지역 지표 — 3km 안에서 닿지 않는 집계구는 거리 3km(하한)로, 30분 밖으로 셈."""
    c.execute(text("DELETE FROM mart.access_metric WHERE calc_run_id = :r AND metric_code = ANY(:m)"),
              {"r": rid, "m": list(WALK_METRICS)})
    c.execute(text("""
        CREATE TEMP TABLE walk_oa ON COMMIT DROP AS
        SELECT n.oa_cd, n.emd_cd, coalesce(n.tot_ppltn, 0) AS pop,
               coalesce(p.walk_m, CAST(:lim AS real)) AS post_m, coalesce(b.walk_m, CAST(:lim AS real)) AS bank_m
          FROM mart.oa_nearest n
          LEFT JOIN mart.oa_walk p ON p.calc_run_id = n.calc_run_id AND p.kind = 'POST' AND p.oa_cd = n.oa_cd AND p.rank = 1
          LEFT JOIN mart.oa_walk b ON b.calc_run_id = n.calc_run_id AND b.kind = 'BANK' AND b.oa_cd = n.oa_cd AND b.rank = 1
         WHERE n.calc_run_id = :r"""), {"r": rid, "lim": limit})
    for level, key in ((3, "emd_cd"), (2, "left(emd_cd, 5)")):
        if level not in levels:
            continue
        c.execute(text(f"""
            INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
            SELECT :r, g.adm_cd, m.code, :lvl, m.v FROM (
                SELECT {key} AS adm_cd, sum(pop) AS pop,
                       sum(pop * post_m) / nullif(sum(pop), 0) AS popw,
                       sum(pop) FILTER (WHERE post_m > :w) AS no_fin,
                       sum(pop) FILTER (WHERE least(post_m, bank_m) > :w) AS no_cash
                  FROM walk_oa GROUP BY 1) g
             JOIN mart.admin_area a ON a.adm_cd = g.adm_cd AND a.level = :lvl
             CROSS JOIN LATERAL (VALUES ('POPW_FIN_WALK_M', round(CAST(g.popw AS numeric), 1)),
                                        ('WALK30_NO_FIN_PPLTN', coalesce(g.no_fin, 0)),
                                        ('WALK30_NO_FIN_SHARE', round(CAST(100.0 * coalesce(g.no_fin, 0) / nullif(g.pop, 0) AS numeric), 1)),
                                        ('WALK30_NO_CASH_PPLTN', coalesce(g.no_cash, 0))) m(code, v)
             WHERE g.pop > 0"""), {"r": rid, "lvl": level, "w": within})
    # 순위·백분위 — 지표 계산과 같은 SQL (전체 다시 매겨도 수 초)
    from atlas.calc.runner import run_sql_file

    run_sql_file(c, "calc/10_ranks.sql", {"calc_run_id": rid})


def _bank_impact(c, rid: uuid.UUID, within: float) -> None:
    """은행 지점 영향평가의 도보 열 — 걸어서 가장 가까운 은행 지점이 X 인 주민 기준.
    잃는 주민 = 지금은 걸어서 30분 안에 X 가 있는데, 닫히면 30분 안에 대체 창구가 없어지는 주민."""
    c.execute(text("""
        WITH oa AS (
            SELECT n.oa_cd, coalesce(n.tot_ppltn, 0) AS pop, b1.target AS x, b1.walk_m AS now_m,
                   least(b2.walk_m, CASE WHEN bi.post_agent THEN p1.walk_m END) AS alt_m
              FROM mart.oa_nearest n
              JOIN mart.oa_walk b1 ON b1.calc_run_id = n.calc_run_id AND b1.kind = 'BANK' AND b1.oa_cd = n.oa_cd AND b1.rank = 1
              JOIN mart.bank_impact bi ON bi.calc_run_id = n.calc_run_id AND bi.place_id = b1.target
              LEFT JOIN mart.oa_walk b2 ON b2.calc_run_id = n.calc_run_id AND b2.kind = 'BANK' AND b2.oa_cd = n.oa_cd AND b2.rank = 2
              LEFT JOIN mart.oa_walk p1 ON p1.calc_run_id = n.calc_run_id AND p1.kind = 'POST' AND p1.oa_cd = n.oa_cd AND p1.rank = 1
             WHERE n.calc_run_id = :r)
        UPDATE mart.bank_impact b
           SET walk_now_m = g.now_m, walk_alt_m = g.alt_m, walk_lost_ppltn = g.lost
          FROM (SELECT x, round(CAST(sum(pop * now_m) / nullif(sum(pop), 0) AS numeric)) AS now_m,
                       round(CAST(sum(pop * alt_m) FILTER (WHERE alt_m IS NOT NULL)
                                  / nullif(sum(pop) FILTER (WHERE alt_m IS NOT NULL), 0) AS numeric)) AS alt_m,
                       coalesce(sum(pop) FILTER (WHERE now_m <= :w AND coalesce(alt_m, 1e9) > :w), 0) AS lost
                  FROM oa GROUP BY x) g
         WHERE b.calc_run_id = :r AND b.place_id = g.x"""), {"r": rid, "w": within})
    c.execute(text("""UPDATE mart.bank_impact SET walk_lost_ppltn = coalesce(walk_lost_ppltn, 0)
                      WHERE calc_run_id = :r"""), {"r": rid})
    c.execute(text("""UPDATE mart.bank_impact
                         SET reasons = mart.bank_impact_reasons(lost_ppltn, same_brand_m, catch_aged, catch_ppltn, walk_lost_ppltn)
                       WHERE calc_run_id = :r"""), {"r": rid})
    c.execute(text("UPDATE mart.bank_impact SET grade = mart.bank_impact_grade(lost_ppltn, reasons) WHERE calc_run_id = :r"),
              {"r": rid})

