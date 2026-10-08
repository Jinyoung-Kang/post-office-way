"""QA 스크립트 공통 — 주소·화면 목록·브라우저 실행·결과 보고."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WEB = os.environ.get("QA_WEB", "http://localhost:3100").rstrip("/")
API = os.environ.get("QA_API", "http://localhost:8100/api/v1").rstrip("/")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".qa"                     # 결과 파일 (git 제외)

# 9개 메뉴 — 지도(카카오 SDK)가 있는 화면은 MAP_PAGES
PAGES = ["/overview", "/", "/today", "/hubs", "/banks", "/rankings", "/whatif", "/plan", "/report/37520", "/quality",
         "/about/metrics"]
MAP_PAGES = ["/", "/today", "/plan", "/banks"]


async def launch(p):
    """설치된 Chrome 사용 — playwright install 없이 동작."""
    return await p.chromium.launch(channel=os.environ.get("QA_CHROME_CHANNEL", "chrome"))


def report(name: str, problems: list, detail: object | None = None) -> None:
    """problems 가 비면 OK(종료 코드 0), 있으면 목록을 찍고 종료 코드 1."""
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps({"problems": problems, "detail": detail}, ensure_ascii=False, indent=1))
    if problems:
        print(f"[{name}] 문제 {len(problems)}건")
        for x in problems[:40]:
            print("  -", x)
        sys.exit(1)
    print(f"[{name}] OK" + (f" — {detail}" if isinstance(detail, str) else ""))
