"""행정안전부 지역별 인구이동(1741000/ppltnDataStus) → mart.migration_month + SGIS 시군구 대응표 (ADR-028).

- 한 달 = 전국→전국 시군구 단위 행렬(lv=2, 약 2.9만 행 · 100행씩 약 290회). 모든 쪽을 빠짐·겹침 없이 받았을 때만
  그 달을 통째로 바꿈 — 일부만 받으면 전입·전출 합이 틀리므로 그 달은 넣지 않고 다음 실행이 처음부터 다시 받음.
  (시군구마다 전입·전출을 따로 부르면 쪽 수가 약 4배 — 행렬 하나에 전입과 전출이 모두 있음)
  쪽 하나가 약 860KB·평균 5초라 제한 시간은 30초, 동시 3개. 실패한 쪽은 그 달 끝에 한 번 더 받아 본 뒤에야 그 달을 포기함
  (첫 백필에서 자정 뒤 서버가 느려져 10초 제한에 걸린 쪽 하나 때문에 9개월이 버려졌음)
- 대상 = 지난 MIGRATION_MONTHS 개 달(이번 달 제외) 중 없는 달 + 공표 직후 받은 달(한 달 뒤 한 번 더 — 값이 고쳐지는지 기록).
  가장 최근 달이 아직 공표 전이면(결과 없음·잘못된 요청) 실패가 아니라 '아직'으로 건너뜀.
- 한도(코드 22) 등으로 멈추면 받은 달까지 남기고 PARTIAL — 커서 없이 다음 실행이 DB 상태로 이어받음.
- 끝나면 시도 코드 개편 별칭(옛 코드 → 새 코드)과 SGIS 시군구(STAT_YEAR) ↔ 행안부 단위 대응표를 다시 만듦:
  KOSIS 코드 → 이름 → 일반구는 그 시. 대응표의 단위 코드는 별칭을 따라간 최신 코드.
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from atlas.collector.datago.client import DataGoStop, call, items_of, make_fetcher
from atlas.collector.http import Fetcher
from atlas.collector.kosis.matching import norm
from atlas.core.clock import KST, now_kst
from atlas.core.config import get_settings
from atlas.core.db import begin
from atlas.domain.migration import NATION_CD, UnitMonth, add_rows, merge, needs_recheck, recent_months
from atlas.ops import runs
from atlas.ops.dq import DQRecorder

log = logging.getLogger(__name__)
KIND = SOURCE = "MOIS_MIGR"
PAGE_ROWS = 100          # 명세 상한 (1~100)
PAGE_TIMEOUT_S = 30.0    # 쪽당 약 860KB·평균 5초 — 공통 10초는 서버가 느릴 때 모자람
CONCURRENCY = 3          # 동시 호출 (공통 4보다 낮게 — 쪽마다 서버가 큰 응답을 만듦)


class MonthIncomplete(RuntimeError):
    """한 달 행렬을 다 받지 못함 — 그 달은 넣지 않음."""


# ------------------------------------------------------------------------------------------------ 받기
def _url() -> str:
    return f"{get_settings().mois_migration_url}/selectPpltnDataStus"


def _params(ym: str, page: int) -> dict[str, Any]:
    return {"mvinAdmmCd": NATION_CD, "mvtAdmmCd": NATION_CD, "srchFrYm": ym, "srchToYm": ym, "lv": 2,
            "type": "JSON", "numOfRows": PAGE_ROWS, "pageNo": page}


Page = tuple[dict[str, UnitMonth], dict[str, int], set[tuple[str, str]]]


def _page(fetcher: Fetcher, ym: str, page: int) -> Page | None:
    """한 쪽 → (단위별 부분합, 행 수, 받은 쌍), 실패하면 None. 원문 대신 부분합만 돌려줘 290쪽을 받아도 메모리가 늘지 않음."""
    body = call(fetcher, _url(), _params(ym, page), SOURCE)
    if body is None:
        return None
    part: dict[str, UnitMonth] = {}
    keys: set[tuple[str, str]] = set()
    st = add_rows(part, items_of(body), ym, keys)
    return part, st, keys


def fetch_month(fetcher: Fetcher, ym: str, newest: bool = False) -> tuple[dict[str, UnitMonth], dict[str, int]] | None:
    """한 달 행렬 → (단위별 합계, 행 수). 가장 최근 달이 공표 전(결과 없음·잘못된 요청 '10')이면 None.
    실패한 쪽은 끝에 한 번 더 받고, 그래도 실패하거나 받은 행이 전체 건수와 다르거나 같은 쌍이 두 번 오면 MonthIncomplete.
    한도 초과는 DataGoStop."""
    first = call(fetcher, _url(), _params(ym, 1), SOURCE, empty_codes=("03", "10") if newest else ("03",))
    if first is None:
        raise MonthIncomplete(f"{ym} 1쪽 실패")
    total = int(first.get("totalCount") or 0) if first else 0
    if total == 0:
        if newest:
            return None
        raise MonthIncomplete(f"{ym} 결과 없음")
    acc: dict[str, UnitMonth] = {}
    seen: set[tuple[str, str]] = set()
    st = add_rows(acc, items_of(first), ym, seen)
    pages = -(-total // PAGE_ROWS)

    def take(got: Page) -> None:
        part, pst, keys = got
        st["dup"] += pst["dup"] + len(keys & seen)
        seen.update(keys)
        st["rows"] += pst["rows"]
        st["skipped"] += pst["skipped"]
        merge(acc, part)

    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY, thread_name_prefix="migr") as pool:
        futs = {pool.submit(_page, fetcher, ym, p): p for p in range(2, pages + 1)}
        try:
            for f in as_completed(futs):
                if (got := f.result()) is None:
                    failed.append(futs[f])
                else:
                    take(got)
        except BaseException:
            pool.shutdown(cancel_futures=True)     # 한도 초과 등 — 남은 쪽을 부르지 않음
            raise
    for p in sorted(failed):                       # 실패한 쪽만 한 번 더 (호출기 안에서도 쪽마다 3회 재시도)
        if (got := _page(fetcher, ym, p)) is None:
            raise MonthIncomplete(f"{ym} {p}쪽 실패 (다시 받아도)")
        take(got)
    st["retried"] = len(failed)
    got = st["rows"] + st["skipped"] + st["dup"]
    if st["dup"] or got != total:
        raise MonthIncomplete(f"{ym} 받은 행 {got} / 전체 {total} (겹침 {st['dup']})")
    return acc, {**st, "total": total, "pages": pages}


def write_month(c, run_id: uuid.UUID, ym: str, acc: dict[str, UnitMonth]) -> dict[str, Any]:
    """그 달을 통째로 바꿈 → {units, moves, revised}. revised: 전에 받은 값과 합이 다름(다시 받은 달만)."""
    prev = c.execute(text("""SELECT count(*), sum(in_cnt), sum(intra_cnt), sum(in_aged65) FROM mart.migration_month
                             WHERE ref_ym = :ym"""), {"ym": ym}).one()
    c.execute(text("DELETE FROM mart.migration_month WHERE ref_ym = :ym"), {"ym": ym})
    c.execute(text("""INSERT INTO mart.migration_month (mois_cd, ref_ym, ctpv_nm, sgg_nm, in_cnt, out_cnt, in_aged65,
                                                        out_aged65, intra_cnt, collect_run_id)
                      VALUES (:cd, :ym, :ctpv, :sgg, :i, :o, :i65, :o65, :intra, :run)"""),
              [{"cd": cd, "ym": ym, "ctpv": u.ctpv_nm, "sgg": u.sgg_nm, "i": u.in_cnt, "o": u.out_cnt, "i65": u.in_aged65,
                "o65": u.out_aged65, "intra": u.intra_cnt, "run": run_id} for cd, u in sorted(acc.items())])
    new = (len(acc), sum(u.in_cnt for u in acc.values()), sum(u.intra_cnt for u in acc.values()),
           sum(u.in_aged65 for u in acc.values()))
    return {"units": new[0], "moves": new[1], "revised": (tuple(prev) != new) if prev[0] else None}


def pending(c, months: list[str], today: date) -> list[str]:
    """받을 달(최신부터) — 없는 달 + 공표 직후 받아 한 번 더 확인할 달."""
    loaded = {r[0]: r[1] for r in c.execute(text("""SELECT ref_ym, max(loaded_at) FROM mart.migration_month
                                                   WHERE ref_ym = ANY(CAST(:m AS text[])) GROUP BY ref_ym"""), {"m": months})}
    return [m for m in months if m not in loaded or needs_recheck(m, loaded[m].astimezone(KST).date(), today)]


# ------------------------------------------------------------------------------------------------ SGIS 시군구 대응
@dataclass(frozen=True)
class AreaRef:
    adm_cd: str
    adm_nm: str          # SGIS 시군구 이름 ('수원시 장안구', '종로구')
    sido_nm: str
    kosis_cd: str | None  # KOSIS 주민등록인구 대응(V6) — 행안부 코드 앞 5자리와 같은 체계


def match_units(areas: list[AreaRef], units: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """SGIS 시군구 → (행안부 단위 코드, KOSIS_CD|NAME|CITY). units = {코드: (시도명, 시군구명)}.
    ① KOSIS 코드 5자리 + '00000' 이 단위에 있으면 그대로. ② 시도·시군구 이름이 같으면(코드가 바뀐 곳).
    ③ 일반구('수원시 장안구')는 그 시 단위('수원시') — 코드(앞 4자리+'0')나 같은 시도 안 이름으로, 이름 앞부분이 시 이름과 같을 때만
       (코드만 보면 43745 증평군이 43740 영동군에 붙음)."""
    by_name = {(norm(c), norm(s)): cd for cd, (c, s) in sorted(units.items())}
    out: dict[str, tuple[str, str]] = {}
    for a in areas:
        direct = f"{a.kosis_cd[:5]}00000" if a.kosis_cd else None
        if direct in units:
            out[a.adm_cd] = (direct, "KOSIS_CD")
        elif cd := by_name.get((norm(a.sido_nm), norm(a.adm_nm))):
            out[a.adm_cd] = (cd, "NAME")
        else:
            first = a.adm_nm.split()[0] if len(a.adm_nm.split()) >= 2 else ""
            city = f"{a.kosis_cd[:4]}000000" if a.kosis_cd else None
            if first.endswith("시") and city in units and norm(units[city][1]) == norm(first):
                out[a.adm_cd] = (city, "CITY")
            elif first.endswith("시") and (cd := by_name.get((norm(a.sido_nm), norm(first)))):
                out[a.adm_cd] = (cd, "CITY")
    return out


@dataclass(frozen=True)
class UnitSpan:
    code: str
    sgg_nm: str
    first_ym: str        # 받아 둔 달 가운데 이 코드가 처음·마지막으로 나온 달
    last_ym: str


def sido_recodes(spans: list[UnitSpan], months: list[str]) -> dict[str, tuple[str, str]]:
    """시도 코드만 바뀐 개편(통합·명칭 변경)의 옛 코드 → (새 코드, 바뀐 달).
    옛 시도(코드 앞 2자리)의 단위가 **모두** 같은 달 뒤로 사라지고, 바로 다음 달에 처음 나타난 새 시도에 같은 이름의 단위가
    하나씩 있을 때만 잇는다(예: 2026-07 광주 29·전남 46 → 전남광주통합특별시 12, 시군구 경계는 그대로).
    일부 구만 바뀐 개편(2026-07 인천 중구·동구·서구 → 제물포구·영종구·서해구·검단구)은 넓이가 바뀌므로 잇지 않는다."""
    months = sorted(set(months))
    by_sido: dict[str, list[UnitSpan]] = {}
    for sp in spans:
        by_sido.setdefault(sp.code[:2], []).append(sp)
    first_of = {k: min(sp.first_ym for sp in v) for k, v in by_sido.items()}
    out: dict[str, tuple[str, str]] = {}
    for old, units in sorted(by_sido.items()):
        ends = {sp.last_ym for sp in units}
        later = [m for m in months if m > max(ends)]
        if len(ends) != 1 or not later:          # 모두 같은 달에 끝나고, 그 뒤에 받은 달이 있어야
            continue
        nxt = later[0]
        for new, nunits in sorted(by_sido.items()):
            if new == old or first_of[new] != nxt:
                continue
            names: dict[str, list[str]] = {}
            for sp in nunits:
                names.setdefault(norm(sp.sgg_nm), []).append(sp.code)
            pairs = {sp.code: names.get(norm(sp.sgg_nm), []) for sp in units}
            if all(len(v) == 1 for v in pairs.values()):
                out.update({o: (v[0], nxt) for o, v in pairs.items()})
                break
    targets: dict[str, int] = {}
    for new, _ in out.values():
        targets[new] = targets.get(new, 0) + 1
    return {o: v for o, v in out.items() if targets[v[0]] == 1}   # 두 옛 단위가 한 새 단위로 가면 잇지 않음


def rebuild_aliases(c, run_id: uuid.UUID) -> dict[str, str]:
    """받아 둔 달 전체로 시도 코드 개편 별칭을 다시 만듦 → {옛 코드: 새 코드}."""
    spans = [UnitSpan(*r) for r in c.execute(text("""
        SELECT mois_cd, (array_agg(sgg_nm ORDER BY ref_ym DESC))[1], min(ref_ym), max(ref_ym)
          FROM mart.migration_month GROUP BY mois_cd"""))]
    months = [r[0] for r in c.execute(text("SELECT DISTINCT ref_ym FROM mart.migration_month"))]
    rec = sido_recodes(spans, months)
    c.execute(text("DELETE FROM mart.migration_unit_alias"))
    if rec:
        c.execute(text("""INSERT INTO mart.migration_unit_alias (mois_cd, unit_cd, from_ym, collect_run_id)
                          VALUES (:o, :n, :ym, :run)"""),
                  [{"o": o, "n": n, "ym": ym, "run": run_id} for o, (n, ym) in sorted(rec.items())])
    return {o: n for o, (n, _) in rec.items()}


def rebuild_map(c, run_id: uuid.UUID, year: int, dq: DQRecorder, alias: dict[str, str]) -> dict[str, Any]:
    """경계 연도 year 의 대응표를 다시 만듦 → {matched, unmatchedAreas, unmatchedUnits, changed}.
    대응은 옛 코드로도 찾고(KOSIS 코드가 경계 연도 기준), 표에는 별칭을 따라간 최신 코드를 넣음."""
    areas = [AreaRef(*r) for r in c.execute(text("""
        SELECT a.adm_cd, a.adm_nm, coalesce(s.adm_nm, ''), r.kosis_cd
          FROM mart.admin_area a
          LEFT JOIN mart.area_population s ON s.adm_cd = a.parent_cd AND s.stat_year = a.stat_year
          LEFT JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = a.stat_year
         WHERE a.stat_year = :y AND a.level = 2 ORDER BY a.adm_cd"""), {"y": year})]
    units = {r[0]: (r[1], r[2]) for r in c.execute(text("""
        SELECT DISTINCT ON (mois_cd) mois_cd, ctpv_nm, sgg_nm FROM mart.migration_month ORDER BY mois_cd, ref_ym DESC"""))}
    if not areas or not units:
        return {"matched": {}, "unmatchedAreas": 0, "unmatchedUnits": 0, "changed": False}
    pairs = {a: (alias.get(m, m), how) for a, (m, how) in match_units(areas, units).items()}
    before = {r[0]: (r[1], r[2]) for r in c.execute(text("""SELECT adm_cd, mois_cd, match_method FROM mart.area_migration_map
                                                           WHERE stat_year = :y"""), {"y": year})}
    c.execute(text("DELETE FROM mart.area_migration_map WHERE stat_year = :y"), {"y": year})
    if pairs:
        c.execute(text("""INSERT INTO mart.area_migration_map (stat_year, adm_cd, mois_cd, match_method, collect_run_id)
                          VALUES (:y, :a, :m, :how, :run)"""),
                  [{"y": year, "a": a, "m": m, "how": how, "run": run_id} for a, (m, how) in sorted(pairs.items())])
    for a in areas:
        if a.adm_cd not in pairs:
            dq.add(c, "MIGR_UNMATCHED", "mart.admin_area", a.adm_cd, {"admNm": a.adm_nm, "sidoNm": a.sido_nm})
    # 가장 최근 달에 있는데 어느 시군구에도 대응되지 않은 단위 — 경계 연도 뒤에 생긴 구(행정구역 개편) 등
    used = {m for m, _ in pairs.values()}
    orphans = c.execute(text("""SELECT mois_cd, ctpv_nm, sgg_nm, ref_ym FROM mart.migration_month
                                WHERE ref_ym = (SELECT max(ref_ym) FROM mart.migration_month)
                                  AND NOT (mois_cd = ANY(CAST(:used AS text[]))) ORDER BY mois_cd"""),
                        {"used": sorted(used)}).all()
    for cd, ctpv, sgg, ym in orphans:
        dq.add(c, "MIGR_UNMATCHED", "mart.migration_month", cd, {"ctpvNm": ctpv, "sggNm": sgg, "refYm": ym})
    methods: dict[str, int] = {}
    for _, how in pairs.values():
        methods[how] = methods.get(how, 0) + 1
    return {"matched": methods, "unmatchedAreas": len(areas) - len(pairs), "unmatchedUnits": len(orphans),
            "changed": before != pairs}


# ------------------------------------------------------------------------------------------------ 실행
def collect_migration(months: int | None = None) -> tuple[uuid.UUID, bool]:
    """→ (collect_run_id, 지표가 바뀔 수 있는지 — 새 달을 넣었거나 대응표가 바뀜). 바뀐 게 없으면 워커가 재계산을 넣지 않음."""
    s = get_settings()
    today = now_kst().date()
    cands = recent_months(today, months or s.migration_months)
    run_id = runs.start_run(KIND, scope=f"{cands[-1]}~{cands[0]};year={s.stat_year}")
    fetcher = make_fetcher(run_id, SOURCE, timeout_s=PAGE_TIMEOUT_S)
    dq = DQRecorder(collect_run_id=run_id)
    stats: dict[str, Any] = {"months": [], "notYet": [], "failedMonths": [], "revised": [], "stoppedBy": None,
                             "rows": 0, "year": s.stat_year}
    t0 = time.monotonic()
    try:
        with begin() as c:
            todo = pending(c, cands, today)
        stats["pending"] = todo
        for ym in todo:
            try:
                got = fetch_month(fetcher, ym, newest=(ym == cands[0]))
            except DataGoStop as e:
                stats["stoppedBy"] = str(e)[:200]
                break
            except MonthIncomplete as e:
                stats["failedMonths"].append(ym)
                with begin() as c:
                    dq.add(c, "FETCH_FAILED", "mart.migration_month", ym, {"error": str(e)[:200]})
                log.warning("migration month incomplete", extra={"refYm": ym, "error": str(e)[:200]})
                continue
            if got is None:
                stats["notYet"].append(ym)
                continue
            acc, st = got
            with begin() as c:
                w = write_month(c, run_id, ym, acc)
            stats["months"].append(ym)
            stats["rows"] += w["units"]
            if w["revised"]:
                stats["revised"].append(ym)
            stats.setdefault("perMonth", {})[ym] = {"pairs": st["rows"], "units": w["units"], "moves": w["moves"],
                                                     "skipped": st["skipped"], "pages": st["pages"], "retried": st["retried"]}
            stats["calls"] = fetcher.calls
            runs.save_stats(run_id, stats)            # 한 달 1~2분 — 진행 상황을 실행 기록에서 볼 수 있게
        with begin() as c:
            alias = rebuild_aliases(c, run_id)
            stats["recoded"] = len(alias)
            stats["map"] = rebuild_map(c, run_id, s.stat_year, dq, alias)
            stats["dq"] = dq.record_checks(c, ("MIGR_UNMATCHED", "FETCH_FAILED"))
        changed = bool(stats["months"]) or stats["map"]["changed"]
        stats.update({"changed": changed, "calls": fetcher.calls, "errors": fetcher.errors,
                      "elapsedMs": int((time.monotonic() - t0) * 1000)})
        trouble = stats["failedMonths"] or stats["stoppedBy"]
        status = "DONE" if not trouble else ("PARTIAL" if stats["months"] else "FAILED")
        error = None
        if trouble:
            error = "; ".join(filter(None, [f"받지 못한 달 {','.join(stats['failedMonths'])}" if stats["failedMonths"] else "",
                                            stats["stoppedBy"] or ""]))
        runs.finish_run(run_id, status, stats, error=error)
        log.info("migration done", extra={"runId": str(run_id), "months": stats["months"], "status": status})
    except BaseException as e:  # Ctrl-C 에도 기록을 닫음(test_layers)
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        fetcher.close()
    return run_id, changed
