"""What-if(문을 닫는다면) 요약 규칙 — 다시 계산한 지역별 결과에서 영향 인구·거리 변화를 셈. DB·HTTP 없음."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def summarize(results: list[dict[str, Any]], pops: dict[str, Any], aged: dict[str, Any] | None = None) -> dict[str, Any]:
    aged = aged or {}
    n = len(results)
    before = [float(r["dist_before_m"]) for r in results if r["dist_before_m"] is not None]
    after = [float(r["dist_after_m"]) for r in results if r["dist_after_m"] is not None]
    inc = [float(r["dist_after_m"]) - float(r["dist_before_m"]) for r in results
           if r["dist_after_m"] is not None and r["dist_before_m"] is not None]
    return {
        "affectedAreas": n,
        "affectedPpltn": sum(int(pops.get(r["adm_cd"]) or 0) for r in results),
        # KOSIS 미적재면 None (0 과 구분)
        "affectedAged65": (sum(int(aged.get(r["adm_cd"]) or 0) for r in results) if aged else None),
        "avgDistBeforeM": round(sum(before) / len(before), 1) if before else None,
        "avgDistAfterM": round(sum(after) / len(after), 1) if after else None,
        "maxIncreaseM": round(max(inc), 1) if inc else None,
        "areasWithoutFacility": sum(1 for r in results if r["dist_after_m"] is None),
    }


def fin_access_loss(results: list[dict[str, Any]], pops: dict[str, Any], bank: dict[str, float],
                     far_m: float) -> dict[str, Any]:
    """④ 문을 닫아 '금융 창구가 2km 안에 하나도 없게 되는' 인구 — 은행 지점 자료가 있을 때만."""
    if not bank:
        return {"lostFinAccessPpltn": None}
    lost = 0
    for r in results:
        b, a, bk = r["dist_before_m"], r["dist_after_m"], bank.get(r["adm_cd"], 1e12)
        if b is not None and float(b) <= far_m and (a is None or float(a) > far_m) and bk > far_m:
            lost += int(pops.get(r["adm_cd"]) or 0)
    return {"lostFinAccessPpltn": lost}


def oa_impact(rows: Sequence[Sequence[Any]], far_m: float) -> dict[str, Any]:
    """① 집계구 단위 — 최근접이 바뀌는 인구와 새로 far_m 밖이 되는 인구(읍면동 대표점 1개보다 정확).
    rows: (인구, 지금 최근접 거리, 닫은 뒤 최근접 거리, 은행 지점 거리, 약국 거리, 의원 거리)."""
    def newly_far(b, a) -> bool:
        return b is not None and float(b) <= far_m and (a is None or float(a) > far_m)

    def none_near(*ds) -> bool:
        return all(d is not None and float(d) > far_m for d in ds)

    # ⑦ 새로 2km 밖이 되면서 은행 지점·약국·의원도 2km 안에 없는 인구 — 문을 닫아 생활 거점을 모두 잃음
    has_life = any(r[4] is not None and r[5] is not None for r in rows)
    return {"oaAffectedPpltn": sum(int(r[0] or 0) for r in rows),
            "oaNewlyFarPpltn": sum(int(r[0] or 0) for r in rows if newly_far(r[1], r[2])),
            "lifeHubLostPpltn": (sum(int(r[0] or 0) for r in rows
                                     if newly_far(r[1], r[2]) and none_near(r[3], r[4], r[5])) if has_life else None)}
