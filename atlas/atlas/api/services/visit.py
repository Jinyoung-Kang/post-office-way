"""⑥ 오늘의 방문 여건 — 시군구별 날씨·대기 판정(VISIT-1) × 우체국에서 먼 고령인구.

판정은 조회 때 계산합니다(시군구 약 250곳 × 운영 시간 10시간 — 수 ms). 규칙이 바뀌어도 재수집 없이 반영됩니다.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from atlas.api import cache
from atlas.api.common import jsonable
from atlas.api.errors import ApiError, bad_request
from atlas.api.services import calendar as cal
from atlas.core.clock import now_kst
from atlas.core.config import get_settings
from atlas.domain.calendar import day_status
from atlas.domain.visit import LEVEL_LABEL, VISIT_RULE_VERSION, WINDOW_HOURS, Hour, air_region, assess

IMPACT_METRICS = ("AGED65_FAR_PPLTN", "FAR2KM_PPLTN", "NEAREST_FIN_DIST_M", "HOLIDAY_CARE_GAP_PPLTN", "HAS_365")


def _latest_calc(c: Connection) -> dict[str, Any] | None:
    r = c.execute(text("""SELECT calc_run_id, stat_year FROM mart.calc_run WHERE status = 'DONE'
                          ORDER BY finished_at DESC NULLS LAST, created_at DESC LIMIT 1""")).mappings().first()
    return dict(r) if r else None


def available_dates(c: Connection, today: date) -> list[date]:
    return [r[0] for r in c.execute(text("""
        SELECT DISTINCT CAST(fcst_at AS date) FROM mart.weather_hourly
         WHERE fcst_at >= CAST(:d AS timestamp) AND EXTRACT(hour FROM fcst_at) BETWEEN :h0 AND :h1
         ORDER BY 1 LIMIT 4"""), {"d": today, "h0": WINDOW_HOURS.start, "h1": WINDOW_HOURS.stop - 1}).all()]


def _hours_by_grid(c: Connection, d: date, grid: tuple[int, int] | None = None) -> dict[tuple[int, int], list[Hour]]:
    out: dict[tuple[int, int], list[Hour]] = defaultdict(list)
    nx, ny = grid or (None, None)
    for r in c.execute(text("""
            SELECT nx, ny, CAST(EXTRACT(hour FROM fcst_at) AS int) AS h, tmp, pop, pty, pcp_mm, sno_cm, wsd
              FROM mart.weather_hourly
             WHERE fcst_at >= CAST(:d AS timestamp) AND fcst_at < CAST(:d AS timestamp) + interval '1 day'
               AND (CAST(:nx AS int) IS NULL OR (nx = CAST(:nx AS int) AND ny = CAST(:ny AS int)))"""),
            {"d": d, "nx": nx, "ny": ny}).mappings():
        f = {k: (float(r[k]) if r[k] is not None else None) for k in ("tmp", "pop", "pcp_mm", "sno_cm", "wsd")}
        out[(r["nx"], r["ny"])].append(Hour(hour=r["h"], pty=r["pty"], **f))
    return out


def _air(c: Connection, d: date) -> tuple[dict[tuple[str, str], str], Any]:
    rows = c.execute(text("""SELECT inform_code, region, grade, announced_at FROM mart.air_forecast
                             WHERE inform_date = :d"""), {"d": d}).all()
    return {(code, region): grade for code, region, grade, _ in rows}, max((r[3] for r in rows), default=None)


def _areas(c: Connection, year: int, calc_run_id: Any, adm_cd: str | None = None) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(text("""
        WITH e AS (   -- 시군구 안 읍면동 중 365코너(ATM)가 없는 곳 — 창구 휴무일에 현금 인출이 어려운 동네
            SELECT left(adm_cd, 5) AS sgg, count(*) FILTER (WHERE value = 0) AS no365, count(*) AS n
              FROM mart.access_metric WHERE calc_run_id = CAST(:run AS uuid) AND metric_code = 'HAS_365' AND level = 3
             GROUP BY 1)
        SELECT a.adm_cd, a.adm_nm, pa.adm_nm AS parent_nm, g.nx, g.ny, max(e.no365) AS emd_no365, max(e.n) AS emd_n,
               max(m.value) FILTER (WHERE m.metric_code = 'AGED65_FAR_PPLTN') AS aged_far,
               max(m.value) FILTER (WHERE m.metric_code = 'FAR2KM_PPLTN') AS far_ppltn,
               max(m.value) FILTER (WHERE m.metric_code = 'NEAREST_FIN_DIST_M') AS nearest_m,
               max(m.value) FILTER (WHERE m.metric_code = 'HOLIDAY_CARE_GAP_PPLTN') AS hcare_gap,
               max(m.value) FILTER (WHERE m.metric_code = 'HAS_365') AS has_365
          FROM mart.admin_area a
          LEFT JOIN mart.area_grid g ON g.adm_cd = a.adm_cd AND g.stat_year = a.stat_year
          LEFT JOIN e ON e.sgg = a.adm_cd
          LEFT JOIN mart.area_population pa ON pa.adm_cd = left(a.adm_cd, 2) AND pa.stat_year = a.stat_year
          LEFT JOIN mart.access_metric m ON m.adm_cd = a.adm_cd AND m.calc_run_id = CAST(:run AS uuid)
                                        AND m.metric_code = ANY(CAST(:codes AS text[]))
         WHERE a.stat_year = :y AND a.level = 2 AND (CAST(:cd AS text) IS NULL OR a.adm_cd = CAST(:cd AS text))
         GROUP BY a.adm_cd, a.adm_nm, pa.adm_nm, g.nx, g.ny ORDER BY a.adm_cd"""),
        {"y": year, "run": str(calc_run_id) if calc_run_id else None, "codes": list(IMPACT_METRICS), "cd": adm_cd}).mappings()]


def _item(a: dict[str, Any], hours: dict[tuple[int, int], list[Hour]], air: dict[tuple[str, str], str]) -> dict[str, Any]:
    region = air_region(a["adm_cd"], a["adm_nm"])
    res = assess(hours.get((a["nx"], a["ny"]), []), air.get(("PM10", region)), air.get(("PM25", region)))
    aged_far = a["aged_far"]
    return jsonable({
        "admCd": a["adm_cd"], "admNm": a["adm_nm"], "parentNm": a["parent_nm"], "airRegion": region,
        "level": res.level, "label": res.label, "reasons": res.reasons, **res.summary,
        "agedFarPpltn": aged_far, "farPpltn": a["far_ppltn"], "nearestFinM": a["nearest_m"],
        # 창구 휴무일(주말·공휴일)에 쓸 수 있는 거점 — 우체국 365코너, 공휴일 진료 약국·의원
        "has365": None if a["has_365"] is None else a["has_365"] >= 1, "holidayCareGapPpltn": a["hcare_gap"],
        "emdWithout365": a["emd_no365"], "emdCount": a["emd_n"],
        # 여건이 주의 이상인 날, 우체국에서 2km 넘게 사는 65세 이상 — 방문이 특히 어려운 사람 수(추정)
        "atRiskAged": aged_far if (res.level or 0) >= 1 else 0,
    })


def _meta(c: Connection, d: date, dates: list[date], air_at: Any, calc: dict[str, Any] | None) -> dict[str, Any]:
    w = c.execute(text("""SELECT max(base_at) FROM mart.weather_hourly
                          WHERE fcst_at >= CAST(:d AS timestamp) AND fcst_at < CAST(:d AS timestamp) + interval '1 day'"""),
                  {"d": d}).scalar()
    today = now_kst().date()
    hol = cal.holidays(c, min([d, *dates]), max([d, *dates]))
    st = day_status(d, hol)
    return jsonable({"date": d, "dates": [{"date": x, "label": _day_label(x, today), **_closed(x, hol)} for x in dates],
                     "closed": st["closed"], "closedReason": st["reason"], "hasCalendar": cal.has_calendar(c, d),
                     "window": f"{WINDOW_HOURS.start:02d}:00~{WINDOW_HOURS.stop - 1:02d}:00",
                     "weatherBaseAt": w, "airAnnouncedAt": air_at, "ruleVersion": VISIT_RULE_VERSION,
                     "calcRunId": calc and calc["calc_run_id"], "levels": LEVEL_LABEL,
                     "note": "기상청 단기예보·에어코리아 예보로 판정한 분석용 참고 정보이며 기상특보가 아닙니다."})


def _closed(d: date, hol: dict[date, str]) -> dict[str, Any]:
    st = day_status(d, hol)
    return {"closed": st["closed"], "closedReason": st["reason"]}


def _no_data() -> ApiError:
    return ApiError(404, "VISIT_NO_DATA",
                    "방문 여건 예보가 없습니다. .env 에 DATA_GO_KR_KEY 를 넣고 `make weather` 를 실행하세요.")


def _pick_date(c: Connection, day: str | None) -> tuple[date, list[date]]:
    now = now_kst()
    dates = available_dates(c, now.date())
    if day:
        try:
            d = date.fromisoformat(day)
        except ValueError as e:
            raise bad_request("date 는 YYYY-MM-DD 입니다.") from e
        return d, dates
    if not dates:
        raise _no_data()
    # 오늘 창구 운영이 끝났으면 내일부터
    upcoming = [x for x in dates if x > now.date() or now.hour < WINDOW_HOURS.stop]
    return (upcoming or dates)[0], dates


def _version(c: Connection, d: date) -> str:
    """판정 입력의 버전 — 이 값이 같으면 결과도 같음(예보 발표·대기 발표·공휴일·계산·오늘 날짜)."""
    v = c.execute(text("""SELECT (SELECT max(base_at) FROM mart.weather_hourly
                                  WHERE fcst_at >= CAST(:d AS timestamp) AND fcst_at < CAST(:d AS timestamp) + interval '1 day'),
                                 (SELECT max(announced_at) FROM mart.air_forecast WHERE inform_date = :d),
                                 (SELECT max(fetched_at) FROM mart.holiday),
                                 (SELECT calc_run_id FROM mart.calc_run WHERE status = 'DONE'
                                   ORDER BY finished_at DESC NULLS LAST, created_at DESC LIMIT 1)"""), {"d": d}).one()
    return "|".join(str(x) for x in (*v, now_kst().date(), VISIT_RULE_VERSION))


def conditions_json(c: Connection, day: str | None, sido: str | None = None) -> str:
    """직렬화된 JSON 문자열. 판정은 250여 시군구 × 시간 예보를 파이썬에서 도는 작업(약 300ms)이라 입력 버전이 같으면
    캐시하고, 적중 시 dict 로 되살렸다 다시 직렬화하지 않고 문자열을 그대로 돌려줌(100KB 응답의 인코딩 비용 제거)."""
    d, dates = _pick_date(c, day)
    key = "visit:" + hashlib.sha1(f"{_version(c, d)}|{d}|{sido}".encode()).hexdigest()[:20]
    if hit := cache.get(key):
        return hit.decode()
    body = json.dumps(_conditions(c, d, dates, sido), ensure_ascii=False, default=str)
    cache.set(key, body, ttl=1800)
    return body


def conditions(c: Connection, day: str | None, sido: str | None = None) -> dict[str, Any]:
    return json.loads(conditions_json(c, day, sido))


def _conditions(c: Connection, d: date, dates: list[date], sido: str | None) -> dict[str, Any]:
    calc = _latest_calc(c)
    year = calc["stat_year"] if calc else get_settings().stat_year
    hours, (air, air_at) = _hours_by_grid(c, d), _air(c, d)
    if not hours and not air:
        raise _no_data()
    items = [_item(a, hours, air) for a in _areas(c, year, calc and calc["calc_run_id"])
             if not sido or a["adm_cd"].startswith(sido)]
    items.sort(key=lambda x: (-(x["level"] if x["level"] is not None else -1), -(x["agedFarPpltn"] or 0), x["admCd"]))
    by_level = {LEVEL_LABEL[k]: sum(1 for x in items if x["level"] == k) for k in LEVEL_LABEL}
    by_level["예보 없음"] = sum(1 for x in items if x["level"] is None)
    reasons: dict[str, int] = defaultdict(int)
    for x in items:
        for r in x["reasons"]:
            reasons[r["code"]] += 1
    return {"meta": _meta(c, d, dates, air_at, calc), "items": items,
            "summary": {"areas": len(items), "byLevel": by_level, "byReason": dict(reasons),
                        "atRiskAged": sum(x["atRiskAged"] or 0 for x in items),
                        "atRiskAreas": sum(1 for x in items if (x["level"] or 0) >= 1),
                        "holidayCareGapPpltn": (sum(x["holidayCareGapPpltn"] or 0 for x in items)
                                                if any(x["holidayCareGapPpltn"] is not None for x in items) else None),
                        "without365Areas": sum(1 for x in items if x["has365"] is False),
                        "emdWithout365": (sum(x["emdWithout365"] or 0 for x in items)
                                          if any(x["emdWithout365"] is not None for x in items) else None)}}


def area_outlook(c: Connection, adm_cd: str) -> dict[str, Any]:
    """지역 카드용 — 시군구(읍면동이면 상위 시군구)의 오늘~모레 판정."""
    sgg = adm_cd[:5]
    if len(adm_cd) < 5 or not sgg.isdigit():
        raise bad_request("admCd 는 시군구(5자리) 또는 읍면동 코드입니다.")
    now = now_kst()
    calc = _latest_calc(c)
    year = calc["stat_year"] if calc else get_settings().stat_year
    areas = _areas(c, year, calc and calc["calc_run_id"], sgg)
    if not areas:
        raise ApiError(404, "AREA_NOT_FOUND", f"시군구 {sgg} 가 없습니다.")
    dates = [x for x in available_dates(c, now.date()) if x > now.date() or now.hour < WINDOW_HOURS.stop]
    days = []
    grid = (areas[0]["nx"], areas[0]["ny"]) if areas[0]["nx"] is not None else (-1, -1)
    hol = cal.holidays(c, now.date(), now.date() + timedelta(days=7))
    for d in dates[:3]:
        hours, (air, _) = _hours_by_grid(c, d, grid), _air(c, d)
        days.append({"date": d.isoformat(), "dayLabel": _day_label(d, now.date()), **_closed(d, hol),
                     **_item(areas[0], hours, air)})
    return {"admCd": sgg, "admNm": areas[0]["adm_nm"], "ruleVersion": VISIT_RULE_VERSION, "days": days}


def _day_label(d: date, today: date) -> str:
    return {0: "오늘", 1: "내일", 2: "모레"}.get((d - today).days, "월화수목금토일"[d.weekday()] + "요일")
