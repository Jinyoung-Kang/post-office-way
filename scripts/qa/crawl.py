"""화면 상호작용 크롤링 — 9개 메뉴를 실제 브라우저로 눌러 보며 콘솔 오류·페이지 오류·HTTP 4xx/5xx 를 모음.

데이터에 따라 없을 수 있는 요소(예: 방문 여건 '주의' 행)는 있을 때만 누릅니다.
"""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from _common import WEB, launch, report

problems: list[str] = []


def note(kind: str, where: str, msg: object) -> None:
    if "/nope" in where:            # 일부러 여는 없는 주소(404 화면 확인)
        return
    problems.append(f"{kind} {where} {str(msg)[:200]}")


async def step(name: str, coro) -> None:
    try:
        await coro
    except Exception as e:  # 단계 실패도 문제로
        note("STEP", name, e)


async def maybe(name: str, loc) -> None:
    """데이터에 따라 없을 수 있는 요소 — 있으면 누름."""
    if await loc.count():
        await step(name, loc.first.click())


async def main() -> None:
    async with async_playwright() as p:
        b = await launch(p)
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
        pg = await ctx.new_page()
        pg.on("console", lambda m: m.type in ("error", "warning") and note("CONSOLE-" + m.type, pg.url, m.text))
        pg.on("pageerror", lambda e: note("PAGEERROR", pg.url, e))
        pg.on("response", lambda r: r.status >= 400 and note("HTTP", r.url, r.status))
        W = lambda ms=1500: pg.wait_for_timeout(ms)  # noqa: E731

        # 한눈에
        await pg.goto(WEB + "/overview", wait_until="networkidle"); await W()
        await step("overview→life", pg.get_by_role("link", name="자세히").first.click()); await W()
        # 지도
        await pg.goto(WEB + "/", wait_until="networkidle"); await W(3000)
        await step("map metric", pg.get_by_label("지표 선택").select_option("POST_SOLE_HUB_PPLTN")); await W(2000)
        await step("map emd", pg.get_by_role("radio", name="읍면동").click()); await W(2500)
        await step("map sido", pg.get_by_label("시도").select_option(label="강원특별자치도")); await W(2500)
        await step("map sgg", pg.get_by_label("시군구").select_option(index=2)); await W(2500)
        box = await pg.locator("div.bg-\\[\\#e8e8ed\\]").first.bounding_box()
        if box:
            await pg.mouse.click(box["x"] + box["width"] * 0.62, box["y"] + box["height"] * 0.5); await W(2000)
        for t in ("우체국 시설 보기", "은행·금고 지점 보기", "약국·의원 보기", "공휴일에 여는 곳만"):
            await step("toggle " + t, pg.get_by_text(t).click()); await W()
        for _ in range(3):
            await step("zoom", pg.mouse.wheel(0, -400)); await W(900)
        await W(2500)
        await pg.keyboard.press("Escape"); await W(500)
        await step("map sigungu", pg.get_by_role("radio", name="시군구 · 전국").click()); await W(2500)
        # 방문 여건
        await pg.goto(WEB + "/today", wait_until="networkidle"); await W(2500)
        tabs = pg.get_by_role("radiogroup", name="날짜").get_by_role("radio")
        for i in range(await tabs.count()):
            await step(f"today tab {i}", tabs.nth(i).click()); await W()
        await maybe("today row", pg.locator("tr.clickable")); await W(2500)
        # 생활 거점
        await pg.goto(WEB + "/hubs", wait_until="networkidle"); await W(2000)
        await step("hubs sido", pg.get_by_label("시도").select_option(label="경상북도")); await W()
        for s in ("금융 대체 불가", "담당 인구", "마지막 거점"):
            await step("hubs sort " + s, pg.get_by_role("radio", name=s).click()); await W(1200)
        await step("hubs next", pg.get_by_role("button", name="다음").click()); await W()
        await step("hubs whatif", pg.get_by_role("link", name="What-if ›").first.click()); await W(2500)
        await step("whatif run from hubs", pg.get_by_role("button", name="계산하기").click()); await W(3000)
        # 지역 순위
        await pg.goto(WEB + "/rankings", wait_until="networkidle"); await W(2000)
        await step("rank metric", pg.get_by_label("지표").select_option("CARE_DESERT_PPLTN")); await W()
        await step("rank level", pg.get_by_role("radio", name="읍면동 · 시도 안").click()); await W()
        await step("rank sido", pg.get_by_label("시도").select_option(label="전라남도")); await W()
        await step("rank sort", pg.get_by_role("radio", name="작은 값 20").click()); await W()
        await step("rank row", pg.locator("tr.clickable").first.click()); await W(2500)
        # What-if
        await pg.goto(WEB + "/whatif", wait_until="networkidle"); await W(1000)
        for name in ("의성우체국", "안계우체국"):
            await step("whatif search", pg.get_by_label("우체국 검색").fill(name)); await W(1300)
            await step("whatif pick", pg.get_by_role("button", name=name).first.click()); await W(500)
        await step("whatif level", pg.get_by_role("radio", name="시군구").click()); await W(300)
        await step("whatif run", pg.get_by_role("button", name="계산하기").click()); await W(3500)
        await pg.goto(pg.url, wait_until="networkidle"); await W(2500)       # 공유 주소로 다시 열기
        # 배치 제안
        await pg.goto(WEB + "/plan", wait_until="networkidle"); await W(2000)
        await step("plan sido", pg.get_by_label("시도").select_option(label="충청북도")); await W()
        await step("plan sgg", pg.get_by_label("시군구").select_option(index=3)); await W()
        await step("plan run close", pg.get_by_role("button", name="제안 받기").click()); await W(5000)
        await step("plan open mode", pg.get_by_role("radio", name="열 곳 찾기").click()); await W(500)
        await step("plan weight", pg.get_by_role("radio", name="전체 인구").click()); await W(300)
        await step("plan run open", pg.get_by_role("button", name="제안 받기").click()); await W(5000)
        # 데이터·운영
        await pg.goto(WEB + "/quality", wait_until="networkidle"); await W(2500)
        copy_all = pg.get_by_role("button", name="모두 복사")
        if await copy_all.is_enabled():
            await step("copy all", copy_all.click()); await W(500)
            clip = await pg.evaluate("navigator.clipboard.readText()")
            if "[" not in clip:
                note("CLIP", "quality", repr(clip[:80]))
        await step("sev", pg.get_by_label("심각도").select_option("WARN")); await W()
        await step("scope all", pg.get_by_role("radio", name="전체 기록").click()); await W()
        # 지표 정의
        await pg.goto(WEB + "/about/metrics", wait_until="networkidle"); await W()
        await step("anchor", pg.get_by_role("link", name="판정 규칙").click()); await W(800)
        # ① 은행 지점 — 등급·정렬·시도 바꾸기, 행 고르기, 다음 쪽
        await pg.goto(WEB + "/banks", wait_until="networkidle"); await W(3000)
        await step("banks grade", pg.get_by_role("radio", name="높음").first.click()); await W()
        await step("banks sido", pg.get_by_label("시도").select_option(label="경상북도")); await W()
        await step("banks sort", pg.get_by_label("정렬").select_option("walk")); await W()
        await maybe("banks row", pg.locator("tr.clickable").nth(1)); await W(2500)
        await step("banks next", pg.get_by_role("button", name="다음").click()); await W()
        # ③ 지역 보고서 — 지표 바꾸기, 시군구 바꾸기
        await pg.goto(WEB + "/report/37520", wait_until="networkidle"); await W(2500)
        for name in ("걸어서 30분 밖", "평균 거리", "고령 비율"):
            await step("report view " + name, pg.get_by_role("radio", name=name).click()); await W(500)
        await step("report sgg", pg.get_by_label("시군구").select_option(index=1)); await W(2500)
        await pg.goto(WEB + "/report", wait_until="networkidle"); await W()
        # 없는 주소 → 404 화면
        await pg.goto(WEB + "/nope", wait_until="networkidle"); await W(800)
        if "이 길은 없습니다" not in await pg.locator("main").inner_text():
            problems.append("404 화면 문구 없음")
        await b.close()
    report("crawl", problems, "11개 화면 상호작용 오류 0건")


if __name__ == "__main__":
    asyncio.run(main())
