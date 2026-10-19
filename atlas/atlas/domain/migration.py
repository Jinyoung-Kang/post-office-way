"""인구 추세 — 행정안전부 지역별 인구이동(1741000/ppltnDataStus) 응답 해석 (순수 함수, 네트워크·DB 없음, ADR-028).

응답 한 행 = (통계년월, 전입 시군구, 전출 시군구) 한 쌍의 이동 인구와 만 0~110세 이상 남녀별 인원.
시군구 단위(lv=2)에서 일반구가 있는 시(수원시 장안구 등)는 시 하나(4111000000 수원시)로 묶여 옵니다.
같은 시군구 안 이동(전입 = 전출)은 따로 세고(intra) 전입·전출에는 넣지 않습니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

AGED_FROM = 65
AGE_MAX = 110          # 만110세이상
NATION_CD = "1000000000"   # 전국 — 전입·전출 행정기관코드에 넣으면 시군구 전체 행렬


@dataclass
class UnitMonth:
    """행안부 시군구 단위 한 곳의 한 달 합계."""

    ctpv_nm: str
    sgg_nm: str
    in_cnt: int = 0
    out_cnt: int = 0
    in_aged65: int = 0
    out_aged65: int = 0
    intra_cnt: int = 0


def _int(v: Any) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


def aged65(item: dict[str, Any]) -> int:
    """만 65세 ~ 만110세이상 남녀 합 (키 이름 끝 공백이 섞여 와도 — 명세의 feml0AgeNmprCnt 처럼)."""
    keys = {k.strip(): v for k, v in item.items()}
    return sum(_int(keys.get(f"{sex}{age}AgeNmprCnt")) for sex in ("male", "feml") for age in range(AGED_FROM, AGE_MAX + 1))


def _code(v: Any) -> str | None:
    s = str(v or "").strip()
    return s if len(s) == 10 and s.isdigit() else None


def add_rows(acc: dict[str, UnitMonth], items: list[dict[str, Any]], ref_ym: str,
             seen: set[tuple[str, str]] | None = None) -> dict[str, int]:
    """응답 한 쪽의 행을 단위별 합계(acc)에 더함 → {rows, skipped, dup}.
    다른 달·코드가 이상한 행은 건너뛰고, 같은 (전입, 전출) 쌍이 두 번 오면(쪽 경계가 밀림) dup 으로 셈."""
    st = {"rows": 0, "skipped": 0, "dup": 0}
    for it in items:
        mvin, mvt = _code(it.get("mvinAdmmCd")), _code(it.get("mvtAdmmCd"))
        if not mvin or not mvt or str(it.get("statsYm") or "").strip() != ref_ym:
            st["skipped"] += 1
            continue
        if seen is not None:
            if (mvin, mvt) in seen:
                st["dup"] += 1
                continue
            seen.add((mvin, mvt))
        tot, old = _int(it.get("totNmprCnt")), aged65(it)
        dst = acc.setdefault(mvin, UnitMonth(str(it.get("mvinCtpvNm") or "").strip(), str(it.get("mvinSggNm") or "").strip()))
        src = acc.setdefault(mvt, UnitMonth(str(it.get("mvtCtpvNm") or "").strip(), str(it.get("mvtSggNm") or "").strip()))
        st["rows"] += 1
        if mvin == mvt:
            dst.intra_cnt += tot
            continue
        dst.in_cnt += tot
        dst.in_aged65 += old
        src.out_cnt += tot
        src.out_aged65 += old
    return st


def merge(acc: dict[str, UnitMonth], part: dict[str, UnitMonth]) -> None:
    """쪽마다 따로 더한 부분합을 전체 합계에 합침."""
    for cd, u in part.items():
        a = acc.setdefault(cd, UnitMonth(u.ctpv_nm, u.sgg_nm))
        a.in_cnt += u.in_cnt
        a.out_cnt += u.out_cnt
        a.in_aged65 += u.in_aged65
        a.out_aged65 += u.out_aged65
        a.intra_cnt += u.intra_cnt


def month_add(ym: str, n: int) -> str:
    y, m = divmod(int(ym[:4]) * 12 + int(ym[4:]) - 1 + n, 12)
    return f"{y:04d}{m + 1:02d}"


def recent_months(today: date, n: int) -> list[str]:
    """이번 달을 빼고 지난 n개 달, 최신부터 (이번 달은 아직 집계 전)."""
    cur = f"{today:%Y%m}"
    return [month_add(cur, -i) for i in range(1, n + 1)]


def needs_recheck(ref_ym: str, loaded_on: date, today: date) -> bool:
    """받은 달을 한 번 더 받을지 — 그 달이 끝나고 한 달이 지나기 전에 받았고, 지금은 한 달이 지났으면.
    (공표 직후 값이 나중에 고쳐지는지 확인 — 달마다 한 번만 다시 받음)"""
    settle = month_add(ref_ym, 2)          # 예: 202609 → 202611 (11월 1일부터는 '굳은' 달로 봄)
    return f"{loaded_on:%Y%m}" < settle <= f"{today:%Y%m}"
