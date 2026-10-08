import { afterEach, describe, expect, it, vi } from "vitest";
import { poll } from "./poller";

afterEach(() => { vi.useRealTimers(); });

describe("poll", () => {
  it("받는 중에 다시 시작해도(탭 복귀) 주기 받기는 하나만", async () => {
    vi.useFakeTimers();
    const pending: (() => void)[] = [];
    let calls = 0;
    const load = () => new Promise<boolean>((res) => { calls++; pending.push(() => res(true)); });
    const p = poll(load, 10_000, () => true);
    p.kick();                                  // 첫 받기가 끝나기 전에 탭이 다시 보임
    pending.splice(0).forEach((f) => f());     // 두 받기 모두 끝남
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toBe(2);
    for (let i = 0; i < 3; i++) {              // 이후 10초마다 한 번씩만
      await vi.advanceTimersByTimeAsync(10_000);
      pending.splice(0).forEach((f) => f());
      await vi.advanceTimersByTimeAsync(0);
    }
    expect(calls).toBe(5);
    p.stop();
  });

  it("보이지 않거나 더 받을 것이 없으면 멈추고, stop 뒤에는 받지 않음", async () => {
    vi.useFakeTimers();
    let calls = 0, visible = true, busy = true;
    const p = poll(async () => { calls++; return busy; }, 1000, () => visible);
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toBe(2);
    visible = false;
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls).toBe(3);                     // 숨겨진 뒤 끝난 받기는 다음을 걸지 않음
    visible = true; busy = false; p.kick();   // 다시 보이면 한 번 받고, 받을 것이 없으면 멈춤
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls).toBe(4);
    p.stop(); p.kick();
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls).toBe(4);
  });
});
