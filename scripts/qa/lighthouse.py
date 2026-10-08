"""Lighthouse 모바일(느린 4G·CPU 4배 감속) 9개 화면 × N회, 중앙값 표 (마크다운).

    python scripts/qa/lighthouse.py [N=3] [화면 경로 …]   — npx lighthouse@12 사용, 전체 약 15~20분
점수는 기록용이고 실패 기준은 접근성 < 100 · CLS > 0.1 만 둡니다(성능 점수는 기기 부하에 따라 흔들림).
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys

from _common import OUT, PAGES, WEB, report

NAMES = {"/overview": "한눈에", "/": "지도", "/today": "방문 여건", "/hubs": "생활 거점", "/banks": "은행 지점",
         "/rankings": "지역 순위", "/whatif": "What-if", "/plan": "배치 제안", "/report/37520": "지역 보고서",
         "/quality": "데이터·운영", "/about/metrics": "지표 정의"}


def run(url: str, path: str) -> dict | None:
    out = OUT / "lh" / (path.strip("/").replace("/", "_") or "root")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["npx", "-y", "lighthouse@12", url, "--quiet", "--chrome-flags=--headless=new",
                        "--only-categories=performance,accessibility,best-practices,seo",
                        "--output=json", f"--output-path={out}.json"], capture_output=True)
    if r.returncode:
        return None
    d = json.loads((out.with_suffix(".json")).read_text())
    c, a = d["categories"], d["audits"]
    if any(v["score"] is None for v in c.values()):
        return None
    return {"scores": [round(v["score"] * 100) for v in c.values()],
            "lcp": a["largest-contentful-paint"]["numericValue"] / 1000,
            "cls": a["cumulative-layout-shift"]["numericValue"], "tbt": a["total-blocking-time"]["numericValue"]}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    pages = sys.argv[2:] or PAGES
    rows, problems = [], []
    print("| 화면 | 성능 | 접근성 | 모범 사례 | SEO | LCP | CLS | TBT |\n|---|---|---|---|---|---|---|---|")
    for path in pages:
        rs = [x for x in (run(WEB + path, path) for _ in range(n)) if x]
        if not rs:
            problems.append(f"{path} 측정 실패")
            continue
        rs.sort(key=lambda r: r["scores"][0])
        m = rs[len(rs) // 2]
        line = (f"| {NAMES.get(path, path)} `{path}` | " + " | ".join(map(str, m["scores"]))
                + f" | {m['lcp']:.1f}초 | {m['cls']:.3f} | {m['tbt']:.0f}ms |")
        print(line, flush=True)
        rows.append(line)
        if m["scores"][1] < 100:
            problems.append(f"{path} 접근성 {m['scores'][1]}")
        if statistics.median(r["cls"] for r in rs) > 0.1:
            problems.append(f"{path} CLS {m['cls']:.3f}")
    report("lighthouse", problems, rows)


if __name__ == "__main__":
    main()
