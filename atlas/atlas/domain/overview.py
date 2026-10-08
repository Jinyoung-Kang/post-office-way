"""전국 개요 집계 규칙 — 지역별 최근접 거리·인구에서 인구 가중 평균, 거리대 분포, '먼 거리' 인구를 셈. DB 없음."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

BANDS = [(0, 1000, "1km 이내"), (1000, 2000, "1–2km"), (2000, 3000, "2–3km"), (3000, 5000, "3–5km"),
         (5000, None, "5km 넘음")]


def distance_summary(dist: Sequence[Mapping[str, Any]], far_m: float, has_aged: bool) -> dict[str, Any]:
    """dist: [{d: 거리 m, pop: 인구, aged: 65세 이상}] → 가중 평균·거리대·먼 거리 인구.
    '먼 거리'는 계산 설정(farKm) 하나로 — 집계구 값과 같은 기준 (예전에는 개요만 2km 고정, R10)."""
    tot_pop = sum(r["pop"] or 0 for r in dist)
    wavg = sum(float(r["d"]) * (r["pop"] or 0) for r in dist) / tot_pop if tot_pop else None
    bands = []
    for lo, hi, label in BANDS:
        rows = [r for r in dist if float(r["d"]) >= lo and (hi is None or float(r["d"]) < hi)]
        pop = sum(r["pop"] or 0 for r in rows)
        aged = sum(r["aged"] or 0 for r in rows)
        bands.append({"label": label, "areas": len(rows), "ppltn": pop,
                      "share": round(100 * pop / tot_pop, 1) if tot_pop else None,
                      "aged65": aged if has_aged else None})
    return {"totPop": tot_pop, "weightedAvgDistM": wavg, "bands": bands,
            "farPpltn": sum(r["pop"] or 0 for r in dist if float(r["d"]) > far_m),
            "farAged": sum(r["aged"] or 0 for r in dist if float(r["d"]) > far_m)}
