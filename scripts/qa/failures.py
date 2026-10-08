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
    # (화면, 실패시킬 API 경로 조각, 상태, 화면에 보여야 할 글자)
    ("/quality", "/api/v1/dq/summary", 500, "점검용 실패"),
    ("/banks?id=NO_SUCH_PLACE", "/api/v1/banks/impact/NO_SUCH_PLACE", 404, "점검용 실패"),
    ("/overview", "/api/v1/overview", 500, "점검용 실패"),
    ("/rankings", "/api/v1/areas?", 500, "점검용 실패"),
]


async def main() -> None:
    problems: list[str] = []
    async with async_playwright() as p:
        b = await launch(p)
        for path, frag, status, expect in CASES:
            ctx = await b.new_context(viewport={"width": 1440, "height": 900})
            pg = await ctx.new_page()
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
            body = json.dumps({"code": "QA_FAIL", "message": "점검용 실패", "traceId": None})

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
            for e in errors:
                problems.append(f"{path}: 처리되지 않은 예외 — {e}")
            await ctx.close()
        await b.close()
    report("failures", problems, f"{len(CASES)}개 실패 상황에서 오류 표시·자리 표시 종료·예외 없음")


if __name__ == "__main__":
    asyncio.run(main())
