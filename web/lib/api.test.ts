import { describe, expect, it, vi } from "vitest";
import { api, cachedApi, clearApiCache, qs } from "./api";

describe("api 경로 검사", () => {
  it("다른 경로로 새는 값은 요청 전에 거절", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    for (const bad of ["/whatif/../admin/jobs", "//evil.example/x", "whatif", "/x\\y", "/a/<script>"]) {
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
