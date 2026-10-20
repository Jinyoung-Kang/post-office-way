"""API 실패 응답 주입 — 요청이 실패해도 화면이 오류를 보여 주고(무한 자리 표시 없음), 처리되지 않은 예외가 없는지.

실제 API 를 고장 낼 수 없으니 브라우저에서 특정 요청만 500·404 로 바꿔 응답합니다(page.route).
리뷰에서 찾은 버그(데이터·운영 요약의 .catch 가 주석 안에 있음, 은행 지점 상세 실패 시 자리 표시가 끝나지 않음)를 고정합니다.

    python scripts/qa/failures.py
"""
from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

from _common import WEB, launch, report

CASES = [
    # (화면, 실패시킬 API 경로 조각, 상태, 화면에 보여야 할 글자[, 오류 코드])
    ("/quality", "/api/v1/dq/summary", 500, "점검용 실패"),
    # 이슈 목록이 실패하면 표에 '조건에 맞는 이슈가 없습니다'가 보였음(받는 중에도)
    ("/quality", "/api/v1/dq/issues", 500, "점검용 실패"),
    ("/banks?id=NO_SUCH_PLACE", "/api/v1/banks/impact/NO_SUCH_PLACE", 404, "점검용 실패"),
    ("/overview", "/api/v1/overview", 500, "점검용 실패"),
    ("/rankings", "/api/v1/areas?", 500, "점검용 실패"),
    # 자료가 아직 없을 때(404 + 코드)는 오류가 아니라 준비 안내 — 판정은 메시지가 아니라 오류 코드로
    ("/overview", "/api/v1/overview", 404, "아직 계산된 데이터가 없습니다", "CALC_RUN_NOT_FOUND"),
    # 은행 지점 목록이 실패하면 상세 칸 자리 표시가 끝나지 않고 목록에는 '조건에 맞는 지점이 없습니다'가 보였음
    ("/banks", "/api/v1/banks/impact?", 500, "점검용 실패"),
    ("/banks", "/api/v1/banks/impact?", 404, "아직 계산된 데이터가 없습니다", "BANK_IMPACT_NOT_FOUND"),
    # 시도 목록(/meta/regions) 실패를 빈 목록으로 삼켜 읍면동 순위는 끝없는 자리 표시, 배치 제안은 이유 없는 비활성 버튼,
    # 보고서 목록은 빈 화면이었음
    ("/rankings?level=3", "/api/v1/meta/regions", 500, "점검용 실패"),
    ("/plan", "/api/v1/meta/regions", 500, "점검용 실패"),
    ("/report", "/api/v1/meta/regions", 500, "점검용 실패"),
    # 지켜야 할 우체국 목록이 실패하면 위에는 오류, 표에는 '조건에 맞는 우체국이 없습니다'가 함께 보였음
    ("/hubs", "/api/v1/hubs/facilities", 500, "점검용 실패"),
]


async def main() -> None:
    problems: list[str] = []
    async with async_playwright() as p:
        b = await launch(p)
        for path, frag, status, expect, *code in CASES:
            ctx = await b.new_context(viewport={"width": 1440, "height": 900})
            pg = await ctx.new_page()
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
            body = json.dumps({"code": code[0] if code else "QA_FAIL", "message": "점검용 실패", "traceId": None})

            async def fail(route, _request, _status=status):
                await route.fulfill(status=_status, content_type="application/json", body=body)

            await pg.route(lambda url, _f=frag: _f in url, fail)
            await pg.goto(WEB + path, wait_until="load")          # 운영 화면은 작업 큐를 계속 새로 고쳐 networkidle 이 오지 않음
            await pg.wait_for_timeout(3500)
            text = await pg.inner_text("main")
            if expect not in text:
                problems.append(f"{path}: {frag} 가 {status} 일 때 오류 문구가 보이지 않음")
            busy = await pg.locator("main [aria-busy='true'], main .skeleton").count()
            if busy:
                problems.append(f"{path}: {frag} 가 {status} 일 때 자리 표시 {busy}개가 남음")
            if "조건에 맞는" in text:
                problems.append(f"{path}: {frag} 가 {status} 일 때 '결과 없음' 문구가 오류와 함께 보임")
            for e in errors:
                problems.append(f"{path}: 처리되지 않은 예외 — {e}")
            await ctx.close()
        await b.close()
    report("failures", problems, f"{len(CASES)}개 실패 상황에서 오류 표시·자리 표시 종료·예외 없음")


if __name__ == "__main__":
    asyncio.run(main())
