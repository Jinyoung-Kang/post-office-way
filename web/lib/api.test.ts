import { describe, expect, it, vi } from "vitest";
import { api, qs } from "./api";

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
