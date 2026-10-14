import { afterEach, describe, expect, it, vi } from "vitest";
import { startRequest, tableView, type Outcome } from "./useApi";
import { ApiError, clearApiCache } from "@/lib/api";

// fetch 를 손으로 끝내는 가짜 — 응답 순서를 바꿔 '늦게 온 이전 응답'을 만들어 봄
function fakeFetch() {
  const calls: { url: string; signal?: AbortSignal; resolve: (body: unknown, status?: number) => void }[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => new Promise((res) => {
    calls.push({ url, signal: init?.signal ?? undefined,
      resolve: (body, status = 200) => res(new Response(JSON.stringify(body), { status })) });
  })));
  return calls;
}
const tick = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => { vi.unstubAllGlobals(); clearApiCache(); });

describe("startRequest", () => {
  it("취소한 요청의 늦은 응답은 버리고, 취소 신호를 fetch 에 전달", async () => {
    const calls = fakeFetch();
    const got: Outcome<{ n: number }>[] = [];
    const cancelA = startRequest<{ n: number }>("/a", undefined, (o) => got.push(o));
    startRequest<{ n: number }>("/b", undefined, (o) => got.push(o));
    cancelA();                                   // 조건이 바뀌어 /a 를 취소
    expect(calls[0].signal?.aborted).toBe(true);
    calls[1].resolve({ n: 2 });
    calls[0].resolve({ n: 1 });                  // 이전 요청이 나중에 도착
    await tick(); await tick();
    expect(got).toEqual([{ data: { n: 2 }, error: null }]);
  });

  it("실패는 ApiError(code·status)로 — 화면이 코드로 판정할 수 있게", async () => {
    const calls = fakeFetch();
    const got: Outcome<unknown>[] = [];
    startRequest("/banks/impact", undefined, (o) => got.push(o));
    calls[0].resolve({ code: "BANK_IMPACT_NOT_FOUND", message: "은행 지점 영향평가 결과가 없습니다" }, 404);
    await tick(); await tick();
    const e = got[0].error as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code]).toEqual([404, "BANK_IMPACT_NOT_FOUND"]);
  });

  it("캐시 요청은 같은 경로를 한 번만 받고, 취소해도 공유 요청은 끊지 않음", async () => {
    const calls = fakeFetch();
    const got: Outcome<unknown>[] = [];
    const cancel = startRequest("/metrics", 60_000, () => got.push({ data: "x", error: null }));
    startRequest("/metrics", 60_000, (o) => got.push(o));
    cancel();
    expect(calls).toHaveLength(1);
    expect(calls[0].signal).toBeUndefined();
    calls[0].resolve({ items: [] });
    await tick(); await tick();
    expect(got).toEqual([{ data: { items: [] }, error: null }]);
  });
});

describe("tableView — 표가 보일 것", () => {
  const n = (d: { items: unknown[] }) => d.items.length;
  it("처음 받는 중이나 실패를 '없음'으로 보이지 않게", () => {
    expect(tableView({ data: null, error: null }, n)).toBe("loading");
    expect(tableView({ data: null, error: new Error("점검용 실패") }, n)).toBe("error");
  });
  it("받았고 비었을 때만 빈 상태, 있으면 행", () => {
    expect(tableView({ data: { items: [] }, error: null }, n)).toBe("empty");
    expect(tableView({ data: { items: [1] }, error: null }, n)).toBe("rows");
  });
});
