"""README 화면 캡처 — 실행 중인 로컬 서비스(http://localhost:3100)를 시스템 Chrome 으로 찍어 docs/images/ 에 저장.

    pip install playwright   (브라우저 다운로드 없이 설치된 Google Chrome 사용)
    python scripts/capture_screens.py

지도 타일이 들어간 화면은 JPEG, 나머지는 PNG. macOS 에서는 sips 로 긴 변 1600px 로 줄여 저장소를 가볍게 유지합니다.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://localhost:3100"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
W, H = 1440, 900
MAX_PX = 1600


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)

        async def shot(name: str, clip_h: int | None = None, jpeg: bool = False) -> None:
            path = OUT / f"{name}.{'jpg' if jpeg else 'png'}"
            opts = {"type": "jpeg", "quality": 82} if jpeg else {}
            clip = {"x": 0, "y": 0, "width": W, "height": clip_h} if clip_h else None
            await page.screenshot(path=path, clip=clip, **opts)
            if shutil.which("sips"):
                subprocess.run(["sips", "-Z", str(MAX_PX), str(path)], check=True, capture_output=True)
            print("saved", path.relative_to(OUT.parents[1]))

        # 한눈에 — 히어로 + 요약 타일 + 거리 분포
        await page.goto(f"{BASE}/overview", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await shot("overview", clip_h=1450)

        # 방문 여건 — 오늘(연휴면 창구 휴무 모드) · 생활 거점 · 데이터·운영(작업 큐)
        await page.goto(f"{BASE}/today", wait_until="networkidle")
        await page.wait_for_timeout(3500)
        await page.evaluate("window.scrollTo(0, 380)")
        await page.wait_for_timeout(1500)
        await shot("today", jpeg=True)
        await page.goto(f"{BASE}/hubs", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.evaluate("window.scrollTo(0, 380)")
        await page.wait_for_timeout(800)
        await shot("hubs")

        # 지도 — 시군구 전국 + 지역 카드 (의성군, 고령인구 2km 밖 지표)
        await page.goto(f"{BASE}/?adm=37520&metric=AGED65_FAR_PPLTN", wait_until="networkidle")
        await page.wait_for_timeout(4000)
        await shot("map", jpeg=True)

        # 지도 — 읍면동 + 시설 레이어
        await page.goto(f"{BASE}/?adm=11010530&metric=NEAREST_FIN_DIST_M", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        await page.get_by_text("우체국 시설 보기").click()
        await page.get_by_text("약국·의원 보기").click()
        await page.wait_for_timeout(3500)
        await shot("map-emd", jpeg=True)

        # What-if — 의성우체국 폐국 가정
        await page.goto(f"{BASE}/whatif", wait_until="networkidle")
        await page.get_by_label("우체국 검색").fill("의성우체국")
        await page.wait_for_timeout(1200)
        await page.get_by_role("button", name="의성우체국").first.click()
        await page.get_by_role("button", name="계산하기").click()
        await page.wait_for_timeout(4000)
        await page.evaluate("window.scrollTo(0, 330)")
        await page.wait_for_timeout(1500)
        await shot("whatif", jpeg=True)

        # 배치 제안 — 경상북도 의성군 폐국 영향 최소
        await page.goto(f"{BASE}/plan", wait_until="networkidle")
        await page.get_by_label("시도").select_option(label="경상북도")
        await page.get_by_label("시군구").select_option(label="의성군")
        await page.get_by_role("button", name="제안 받기").click()
        await page.wait_for_timeout(5000)
        await page.evaluate("window.scrollTo(0, 330)")
        await page.wait_for_timeout(1500)
        await shot("plan", jpeg=True)

        # 지역 순위 · 데이터 품질
        await page.goto(f"{BASE}/rankings", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, 330)")
        await page.wait_for_timeout(800)
        await shot("rankings")
        await page.goto(f"{BASE}/quality", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, 300)")
        await page.wait_for_timeout(800)
        await shot("quality")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
