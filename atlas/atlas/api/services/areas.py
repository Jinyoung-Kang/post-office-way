"""지역 조회 — 단계구분도 GeoJSON(캐시), 지표 순위 목록, 지역 상세 카드 (FR-304, FR-501, FR-502)."""
from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api import cache
from atlas.api.common import (FACILITY_COLS, bad_request, jsonable, meta_of, metric_row, not_found,
                              page_params, resolve_calc_run)

DEFAULT_SIMPLIFY = {2: 200.0, 3: 50.0}

# 지표 값 + 레벨 전체 기준 순위(1 = 값이 가장 큼)·백분위(값 오름차순 0~100)
# 순위·백분위는 계산 때 미리 넣어 둔 열(V14, calc/10_ranks.sql)을 읽기만 함
_RANKED = """
    SELECT adm_cd, value, rnk, pct, n
      FROM mart.access_metric
     WHERE calc_run_id = :run AND metric_code = :metric AND level = :level AND value IS NOT NULL
"""


def _check_level(level: int, parent: str | None, run: dict[str, Any]) -> None:
    if level not in (2, 3):
        raise bad_request("level 은 2(시군구) 또는 3(읍면동) 입니다.")
    if level == 3 and not parent:
        raise bad_request("level=3 이면 parent(시도 2자리 또는 시군구 5자리)가 필요합니다.")
    if level not in [int(x) for x in run["params"].get("levels", [])]:
        raise not_found("LEVEL_NOT_CALCULATED", f"calcRunId {run['calc_run_id']} 는 level {level} 을 계산하지 않았습니다.")


def geojson_payload(c: Connection, level: int, metric: str, parent: str | None, calc_run_id: str | None,
                    simplify: float | None, etag_only: bool = False) -> tuple[bytes | None, str]:
    """(gzip 본문, ETag). 캐시에는 gzip 으로 저장해 요청마다 수백 KB 를 다시 압축하지 않고,
    ETag 는 따로 두어 If-None-Match 가 같으면 본문을 Redis 에서 꺼내지도 않습니다(etag_only)."""
    run = resolve_calc_run(c, calc_run_id)
    _check_level(level, parent, run)
    if simplify is not None and not 0 <= simplify <= 5000:
        raise bad_request("simplify 는 0~5000(m) 입니다.")
    key = f"geo:gz:{run['calc_run_id']}:{level}:{parent or '-'}:{metric}:{simplify if simplify is not None else 'd'}"
    if (tag := cache.get(key + ":etag")) and (etag_only or (body := cache.get(key))):
        return (None if etag_only else body), tag.decode()
    raw = geojson(c, level, metric, parent, calc_run_id, simplify).encode()
    gz = gzip.compress(raw, compresslevel=6, mtime=0)          # mtime=0 → 같은 내용이면 같은 바이트
    tag = 'W/"' + hashlib.blake2b(gz, digest_size=12).hexdigest() + '"'
    cache.set(key, gz)
    cache.set(key + ":etag", tag)
    return gz, tag


def geojson(c: Connection, level: int, metric: str, parent: str | None, calc_run_id: str | None,
            simplify: float | None) -> str:
    run = resolve_calc_run(c, calc_run_id)
    _check_level(level, parent, run)
    mdef = metric_row(c, metric)
    if simplify is not None and not 0 <= simplify <= 5000:
        raise bad_request("simplify 는 0~5000(m) 입니다.")

    if simplify is None or simplify == DEFAULT_SIMPLIFY[level]:
        geom = "coalesce(a.geom_simple, a.geom)"
    elif simplify == 0:
        geom = "a.geom"
    else:
        geom = "ST_Transform(ST_SimplifyPreserveTopology(a.geom_5179, CAST(:tol AS float8)), 4326)"
    fc = c.execute(text(f"""
        WITH m AS ({_RANKED})
        SELECT CAST(json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                 'type', 'Feature', 'id', a.adm_cd,
                 'properties', json_build_object('admCd', a.adm_cd, 'admNm', a.adm_nm, 'level', a.level,
                     'parentCd', a.parent_cd, 'value', m.value, 'unit', CAST(:unit AS text), 'rank', m.rnk, 'rankOf', m.n,
                     'percentile', m.pct, 'totPpltn', p.tot_ppltn, 'agedChildIdx', p.aged_child_idx),
                 'geometry', CAST(ST_AsGeoJSON({geom}, 5) AS json)) ORDER BY a.adm_cd), CAST('[]' AS json))) AS text)
          FROM mart.admin_area a
          LEFT JOIN m ON m.adm_cd = a.adm_cd
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
         WHERE a.stat_year = :year AND a.level = :level
           AND (CAST(:parent AS text) IS NULL OR a.adm_cd LIKE CAST(:parent AS text) || '%')
    """), {"run": run["calc_run_id"], "metric": metric, "level": level, "year": run["stat_year"],
           "parent": parent, "unit": mdef["unit"], "tol": simplify}).scalar_one()
    meta = meta_of(run, metric=metric, metricName=mdef["name_ko"], unit=mdef["unit"],
                   higherIsWorse=mdef["higher_is_worse"], level=level, parent=parent, crs="EPSG:4326")
    # text 로 받아 그대로 이어 붙임 — json 으로 받으면 드라이버가 수 MB 를 dict 로 파싱했다가 다시 직렬화함
    fc_text = fc if isinstance(fc, str) else json.dumps(fc, ensure_ascii=False)
    return '{"meta":' + json.dumps(meta, ensure_ascii=False) + "," + fc_text.lstrip()[1:]


def list_areas(c: Connection, level: int, metric: str, parent: str | None, calc_run_id: str | None,
               sort: str, page: int, size: int) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    _check_level(level, None if level == 2 else parent or "x", run)
    mdef = metric_row(c, metric)
    page, size, offset = page_params(page, size)
    if sort not in ("desc", "asc"):
        raise bad_request("sort 는 desc 또는 asc 입니다.")
    params = {"run": run["calc_run_id"], "metric": metric, "level": level, "year": run["stat_year"],
              "parent": parent, "lim": size, "off": offset}
    where = """a.stat_year = :year AND a.level = :level
               AND (CAST(:parent AS text) IS NULL OR a.adm_cd LIKE CAST(:parent AS text) || '%')"""
    total = c.execute(text(f"SELECT count(*) FROM mart.admin_area a WHERE {where}"), params).scalar_one()
    rows = c.execute(text(f"""
        WITH m AS ({_RANKED})
        SELECT a.adm_cd, a.adm_nm, a.parent_cd, pa.adm_nm AS parent_nm, m.value, m.rnk, m.n, m.pct,
               p.tot_ppltn, p.aged_child_idx, ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon
          FROM mart.admin_area a
          LEFT JOIN m ON m.adm_cd = a.adm_cd
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE {where}
         ORDER BY m.value {sort} NULLS LAST, a.adm_cd
         LIMIT :lim OFFSET :off"""), params).mappings().all()
    items = [jsonable({"admCd": r["adm_cd"], "admNm": r["adm_nm"], "parentCd": r["parent_cd"],
                       "parentNm": r["parent_nm"], "value": r["value"], "rank": r["rnk"], "rankOf": r["n"],
                       "percentile": r["pct"], "totPpltn": r["tot_ppltn"], "agedChildIdx": r["aged_child_idx"],
                       "lat": r["lat"], "lon": r["lon"]}) for r in rows]
    return {"items": items, "page": page, "size": size, "total": total,
            "metric": jsonable({"code": metric, "name": mdef["name_ko"], "unit": mdef["unit"],
                                "higherIsWorse": mdef["higher_is_worse"]}),
            "meta": meta_of(run, level=level, parent=parent)}


def area_detail(c: Connection, adm_cd: str, calc_run_id: str | None) -> dict[str, Any]:
    run = resolve_calc_run(c, calc_run_id)
    a = c.execute(text("""
        SELECT a.adm_cd, a.adm_nm, a.level, a.parent_cd, pa.adm_nm AS parent_nm, a.src_crs,
               ST_Y(a.rep_point) AS lat, ST_X(a.rep_point) AS lon,
               ST_XMin(a.geom) AS minx, ST_YMin(a.geom) AS miny, ST_XMax(a.geom) AS maxx, ST_YMax(a.geom) AS maxy,
               round(CAST(ST_Area(a.geom_5179) / 1e6 AS numeric), 2) AS area_km2,
               p.tot_ppltn, p.ppltn_dnsty, p.aged_child_idx, p.avg_age, p.loaded_at AS pop_loaded_at
          FROM mart.admin_area a
          LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = a.stat_year
          LEFT JOIN mart.area_population pa ON pa.adm_cd = a.parent_cd AND pa.stat_year = a.stat_year
         WHERE a.adm_cd = :cd AND a.stat_year = :y"""), {"cd": adm_cd, "y": run["stat_year"]}).mappings().first()
    if not a:
        raise not_found("AREA_NOT_FOUND", f"admCd {adm_cd} ({run['stat_year']}년) 가 없습니다.")
    metrics = c.execute(text("""
        SELECT d.metric_code, d.name_ko, d.unit, d.higher_is_worse, m.value, m.rnk, m.pct, m.n
          FROM mart.access_metric m
          JOIN mart.metric_def d ON d.metric_code = m.metric_code
         WHERE m.calc_run_id = :run AND m.adm_cd = :cd
         ORDER BY d.sort_order, d.metric_code"""),
        {"run": run["calc_run_id"], "lvl": a["level"], "cd": adm_cd}).mappings().all()
    nearest = c.execute(text(f"""
        SELECT n.rank, n.dist_m, r.road_m, r.drive_s, {FACILITY_COLS}
          FROM mart.area_nearest n JOIN mart.post_facility_hist h ON h.hist_id = n.hist_id
          LEFT JOIN mart.area_road r ON r.adm_cd = n.adm_cd AND r.stat_year = :y AND r.hist_id = n.hist_id AND r.status = 'OK'
         WHERE n.calc_run_id = :run AND n.adm_cd = :cd ORDER BY n.rank"""),
        {"run": run["calc_run_id"], "cd": adm_cd, "y": run["stat_year"]}).mappings().all()
    banks = c.execute(text("""
        SELECT b.name, b.addr, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
               round(CAST(ST_Distance(b.geom_5179, a.rep_point_5179) AS numeric), 1) AS dist_m
          FROM mart.admin_area a
         CROSS JOIN LATERAL (SELECT * FROM mart.bank_place b WHERE b.kind = 'BRANCH'
                              ORDER BY b.geom_5179 <-> a.rep_point_5179 LIMIT 3) b
         WHERE a.adm_cd = :cd AND a.stat_year = :y"""), {"cd": adm_cd, "y": run["stat_year"]}).mappings().all()
    fac_counts = c.execute(text("""
        SELECT h.post_div, count(*) AS n, count(*) FILTER (WHERE h.fin_available) AS fin
          FROM mart.facility_area_map m JOIN mart.post_facility_hist h ON h.hist_id = m.hist_id
         WHERE m.stat_year = :y AND m.level = :lvl AND m.adm_cd = :cd
           AND h.valid_from <= :asof AND (h.valid_to IS NULL OR h.valid_to > :asof)
         GROUP BY h.post_div ORDER BY h.post_div"""),
        {"y": run["stat_year"], "lvl": a["level"], "cd": adm_cd, "asof": run["facility_as_of"]}).mappings().all()
    resident = c.execute(text("""SELECT ref_period, tot_ppltn, aged65_ppltn, aged65_ratio, match_method, loaded_at
                                 FROM mart.area_resident_pop WHERE adm_cd = :cd AND stat_year = :y"""),
                         {"cd": adm_cd, "y": run["stat_year"]}).mappings().first()
    from atlas.domain.rules import POST_DIV_LABEL

    return jsonable({
        "admCd": a["adm_cd"], "admNm": a["adm_nm"], "level": a["level"], "parentCd": a["parent_cd"],
        "parentNm": a["parent_nm"], "statYear": run["stat_year"], "areaKm2": a["area_km2"],
        "repPoint": {"lat": a["lat"], "lon": a["lon"]}, "bbox": [a["minx"], a["miny"], a["maxx"], a["maxy"]],
        "population": {"totPpltn": a["tot_ppltn"], "ppltnDnsty": a["ppltn_dnsty"],
                       "agedChildIdx": a["aged_child_idx"], "avgAge": a["avg_age"],
                       "loadedAt": a["pop_loaded_at"]},
        "residentPop": ({"refPeriod": resident["ref_period"], "totPpltn": resident["tot_ppltn"],
                         "aged65Ppltn": resident["aged65_ppltn"], "aged65Ratio": resident["aged65_ratio"],
                         "matchMethod": resident["match_method"], "loadedAt": resident["loaded_at"],
                         "source": "KOSIS 주민등록인구(행정안전부)"} if resident else None),
        "metrics": [{"code": m["metric_code"], "name": m["name_ko"], "value": m["value"], "unit": m["unit"],
                     "higherIsWorse": m["higher_is_worse"], "rank": m["rnk"], "rankOf": m["n"],
                     "percentile": m["pct"]} for m in metrics],
        "nearestBanks": [{"name": b["name"], "addr": b["addr"], "distM": b["dist_m"], "lat": b["lat"], "lon": b["lon"]}
                         for b in banks if b["dist_m"] is not None and b["dist_m"] <= 20000],
        "nearest": [{"rank": n["rank"], "histId": n["hist_id"], "name": n["name"], "distM": n["dist_m"],
                     "roadM": n["road_m"], "driveMin": round(n["drive_s"] / 60, 1) if n["drive_s"] is not None else None,
                     "finAvailable": n["fin_available"], "addr": n["addr"], "financeTime": n["finance_time"],
                     "lat": n["lat"], "lon": n["lon"]} for n in nearest],
        "facilities": [{"postDiv": f["post_div"], "divLabel": POST_DIV_LABEL.get(f["post_div"], "기타"),
                        "count": f["n"], "finCount": f["fin"]} for f in fac_counts],
        "meta": meta_of(run),
    })
