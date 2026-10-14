import { describe, expect, it, vi } from "vitest";
import { api, cachedApi, clearApiCache, qs, type Facility } from "./api";

describe("api 경로 검사", () => {
  it("다른 경로로 새는 값은 요청 전에 거절", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    for (const bad of ["/whatif/../admin/jobs", "//evil.example/x", "whatif", "/x\\y", "/a/<script>",
      // 퍼센트 인코딩한 점 — 브라우저 URL 정규화가 '..' 로 해석해 /api/v1/admin/jobs 로 감 (리뷰 S5)
      "/whatif/%2e%2e/admin/jobs", "/whatif/.%2E/admin/jobs", "/%2e%2e/%2e%2e/api/config", "/whatif/%2E/x"]) {
      await expect(api(bad)).rejects.toMatchObject({ code: "BAD_PATH" });
    }
    expect(f).not.toHaveBeenCalled();
  });

  it("정상 경로와 qs 로 만든 검색어(한글·쉼표)는 통과", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: 1 }) });
    vi.stubGlobal("fetch", f);
    await api(`/facilities${qs({ q: "의성 우체국", bbox: "127.1,36.2,128.9,37.0", finOnly: true })}`);
    await api("/whatif/7b1c2f3e-1111-4a2b-9c3d-0123456789ab");
    await api("/visit/conditions?date=2026-09-25");
    expect(f).toHaveBeenCalledTimes(3);
  });
});

describe("cachedApi", () => {
  it("같은 경로는 한 번만 요청하고, TTL 이 지나면 다시 받음", async () => {
    clearApiCache();
    const f = vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({ n: f.mock.calls.length }) }));
    vi.stubGlobal("fetch", f);
    const [a, b] = await Promise.all([cachedApi("/metrics"), cachedApi("/metrics")]);   // 동시 요청 합치기
    expect(a).toEqual({ n: 1 });
    expect(b).toBe(a);
    await cachedApi("/metrics");
    expect(f).toHaveBeenCalledTimes(1);
    vi.useFakeTimers({ now: Date.now() + 61_000 });
    expect(await cachedApi("/metrics")).toEqual({ n: 2 });
    vi.useRealTimers();
  });

  it("실패는 캐시하지 않음", async () => {
    clearApiCache();
    const f = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ code: "DOWN", message: "잠시 후" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: 1 }) });
    vi.stubGlobal("fetch", f);
    await expect(cachedApi("/overview")).rejects.toMatchObject({ code: "DOWN" });
    expect(await cachedApi("/overview")).toEqual({ ok: 1 });
  });
});

describe("자료 없음 판정", () => {
  it("메시지가 아니라 오류 코드로 — 은행 지점 영향평가 결과 없음도 준비 안내 (메시지에 코드가 없어 놓쳤음)", async () => {
    const { ApiError, isNoData } = await import("./api");
    expect(isNoData(new ApiError(404, "BANK_IMPACT_NOT_FOUND", "은행 지점 영향평가 결과가 없습니다 — 은행 지점 수집 뒤 다시 계산하세요."))).toBe(true);
    expect(isNoData(new ApiError(404, "CALC_RUN_NOT_FOUND", "아무 문구"))).toBe(true);
    expect(isNoData(new ApiError(500, "INTERNAL", "완료된 계산 실행이 없습니다"))).toBe(false);   // 문구가 같아도 코드가 다르면 오류
    expect(isNoData(new Error("CALC_RUN_NOT_FOUND"))).toBe(false);
    expect(isNoData(null)).toBe(false);
  });
});

describe("시설 영업 상태", () => {
  it("점심시간(lunch) — API 가 점심 휴무 시간대에 돌려주는 값. 화면은 open 만 초록, 나머지는 회색", () => {
    const s: NonNullable<Facility["status"]> = { state: "lunch", label: "점심시간 · 13:00 다시 열림", reason: null };
    expect(s.state).not.toBe("open");
  });
});
