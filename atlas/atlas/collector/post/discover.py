"""우편 지역코드 자동 탐색 — 명세서 지역코드표가 없을 때 seed 를 만듭니다.

명세 예시 "100"(서울 중구 일대), "367"(괴산군·증평군)처럼 코드가 옛 우편번호 앞 3자리와 같은
체계로 보여, 기본 범위 100~799 를 pageCount=1 로 한 번씩 호출해 totalCount>0 인 코드만 남깁니다.
(약 700회 × 지연 300ms ≈ 4~5분, 하루 1회 수준)
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from atlas.collector import runs
from atlas.collector.http import Fetcher
from atlas.collector.post.parser import normalize_item
from atlas.collector.post.pipeline import fetch_area
from atlas.collector.post.seed import AreaCode, load_area_codes, write_area_codes
from atlas.core.config import get_settings

log = logging.getLogger(__name__)


def _region_of(addr: str | None) -> tuple[str, str]:
    parts = (addr or "").split()
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def discover(start: int = 100, end: int = 799, extra: list[str] | None = None,
             sleep: Callable[[float], None] = time.sleep) -> tuple[str, int]:
    s = get_settings()
    if not s.post_service_key:
        raise RuntimeError("POST_SERVICE_KEY 가 비어 있습니다 (.env 확인).")
    run_id = runs.start_run("POST_DISCOVER", scope=f"{start}-{end}")
    fetcher = Fetcher(run_id, "POST_AREA", secrets=[s.post_service_key])
    existing = {c.code: c for c in load_area_codes()}
    found: dict[str, AreaCode] = {}
    stats = {"calls": 0, "found": 0, "failedCodes": [], "firstError": None}
    t0 = time.monotonic()
    candidates = [str(n) for n in range(start, end + 1)] + list(extra or [])
    try:
        for i, code in enumerate(candidates):
            res, parsed = fetch_area(fetcher, code, 1, page_size=1, sleep=sleep)
            if not res.ok or parsed is None or parsed.error:
                stats["failedCodes"].append(code)
                stats["firstError"] = stats["firstError"] or (res.error or (parsed.error if parsed else None))
                # 첫 10개가 모두 실패하면 키·주소 문제일 가능성이 커서 중단
                if i == 9 and len(stats["failedCodes"]) == 10:
                    raise RuntimeError(f"처음 10개 코드가 모두 실패했습니다: {stats['firstError']}")
            elif (parsed.total_count or len(parsed.items)) > 0:
                rec = normalize_item(parsed.items[0], code) if parsed.items else {}
                region, sub = _region_of(rec.get("addr"))
                prev = existing.get(code)
                found[code] = AreaCode(code=code, region=prev.region if prev and prev.region else region,
                                       subregion=prev.subregion if prev and prev.subregion else sub,
                                       is_center=bool(prev and prev.is_center) or code.lower().startswith("c"),
                                       total_count=parsed.total_count)
            sleep(s.post_call_delay_ms / 1000)
            if i % 50 == 0:
                log.info("discover progress", extra={"at": code, "found": len(found)})
        stats.update({"calls": fetcher.calls, "found": len(found), "elapsedMs": int((time.monotonic() - t0) * 1000)})
        if not found:
            raise RuntimeError(f"찾은 지역코드가 없습니다. 첫 오류: {stats['firstError']}")
        # 기존 seed 에만 있던 코드(명세서에서 옮겨 적은 c 코드 등)는 유지
        merged = {**{k: v for k, v in existing.items() if k not in found}, **found}
        path = write_area_codes(sorted(merged.values(), key=lambda c: (c.code.lower().startswith("c"), c.code)))
        runs.finish_run(run_id, "DONE" if not stats["failedCodes"] else "PARTIAL", stats)
        return str(path), len(found)
    except Exception as e:
        stats["calls"] = fetcher.calls
        runs.finish_run(run_id, "FAILED", stats, error=str(e))
        raise
    finally:
        fetcher.close()
