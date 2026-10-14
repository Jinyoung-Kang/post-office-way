// 카카오 지도 SDK 로더 — 본체(kakao.js)가 막혀도 끝없이 기다리지 않는지 (window·document·fetch 를 흉내)
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type El = { tagName: string; src: string; async?: boolean; onload?: () => void; onerror?: () => void; remove: () => void };
type Listener = (e: unknown) => void;

const BODY = "https://t1.kakaocdn.net/mapjsapi/js/main/4.4.19/kakao.js";

// sdk.js 를 붙이면 onload, maps.load 를 부르면 body() 가 정한 대로 본체를 '받음'
function setup(body: (fire: (type: string, e: unknown) => void, done: () => void) => void, opts: { noLoad?: boolean } = {}) {
  const listeners: Record<string, Set<Listener>> = {};
  const appended: El[] = [];
  const win: { kakao?: { maps: Record<string, unknown> } } = {};
  const fire = (type: string, e: unknown) => [...(listeners[type] ?? [])].forEach((f) => f(e));
  const doc = {
    addEventListener: (t: string, f: Listener) => { (listeners[t] ??= new Set()).add(f); },
    removeEventListener: (t: string, f: Listener) => { listeners[t]?.delete(f); },
    createElement: (tag: string): El => ({ tagName: tag.toUpperCase(), src: "", remove: () => undefined }),
    head: {
      appendChild: (el: El) => {
        appended.push(el);
        if (el.src.includes("dapi.kakao.com")) {
          win.kakao = { maps: opts.noLoad ? {} : {
            load: vi.fn((cb: () => void) => body(fire, () => { win.kakao!.maps.LatLng = class {}; cb(); })),
          } };
          queueMicrotask(() => el.onload?.());
        }
      },
    },
  };
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ kakaoJsKey: "test-key" }) });
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", doc);
  vi.stubGlobal("fetch", fetch);
  return { win, appended, fetch, listeners };
}

// 정해진 시간 안에 끝나지 않으면 '아직 기다림'으로 끝냄 — 끝없이 기다리는 버그를 테스트 시간 초과 대신 실패로 보이게
function within<T>(p: Promise<T>, ms = 300): Promise<T | "아직 기다림"> {
  return Promise.race([p, new Promise<"아직 기다림">((r) => setTimeout(() => r("아직 기다림"), ms))]);
}

let loadKakao: () => Promise<unknown>;
beforeEach(async () => {
  vi.resetModules();
  ({ loadKakao } = await import("./kakao"));
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("카카오 지도 SDK 로더", () => {
  it("본체 스크립트가 막히면(로드 실패) 거부하고, 다시 부르면 로더를 다시 붙이지 않고 본체만 다시 받음", async () => {
    let attempt = 0;
    const { win, appended, fetch, listeners } = setup((fire, done) => {
      attempt += 1;
      if (attempt === 1) fire("error", { target: { tagName: "SCRIPT", src: BODY } });   // 광고 차단·CDN 이동
      else done();
    });
    await expect(within(loadKakao())).rejects.toThrow(/카카오 지도/);
    expect(listeners.error?.size ?? 0).toBe(0);                   // 기다리던 리스너 정리
    expect(listeners.securitypolicyviolation?.size ?? 0).toBe(0);

    expect(await within(loadKakao())).toBe(win.kakao);           // 같은 SPA 세션에서 다시 시도
    expect(appended.filter((e) => e.src.includes("sdk.js"))).toHaveLength(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(win.kakao!.maps.load).toHaveBeenCalledTimes(2);
  });

  it("본체가 CSP 로 막히면 거부 — 일부러 막은 eval 시도는 무시", async () => {
    setup((fire) => {
      fire("securitypolicyviolation", { blockedURI: "eval", effectiveDirective: "script-src", violatedDirective: "script-src" });
      fire("securitypolicyviolation", { blockedURI: BODY, effectiveDirective: "script-src-elem", violatedDirective: "script-src-elem" });
    });
    await expect(within(loadKakao())).rejects.toThrow(/카카오 지도/);
  });

  it("카카오가 아닌 스크립트 오류·eval 차단만 있으면 그대로 기다렸다가 본체가 오면 성공", async () => {
    const { win } = setup((fire, done) => {
      fire("error", { target: { tagName: "SCRIPT", src: "https://example.com/other.js" } });
      fire("error", { target: { tagName: "IMG", src: "https://mts.daumcdn.net/tile.png" } });
      fire("securitypolicyviolation", { blockedURI: "eval", effectiveDirective: "script-src", violatedDirective: "script-src" });
      done();
    });
    expect(await within(loadKakao())).toBe(win.kakao);
  });

  it("sdk.js 를 받았는데 maps.load 가 없으면 거부", async () => {
    setup(() => undefined, { noLoad: true });
    await expect(within(loadKakao())).rejects.toThrow(/카카오 지도/);
  });

  it("아무 신호 없이 본체가 오지 않으면 오래 기다린 뒤 거부(마지막 수단)", async () => {
    vi.useFakeTimers();
    setup(() => undefined);
    const p = loadKakao();
    const seen = p.then(() => "성공", (e: Error) => e.message);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(await seen).toMatch(/카카오 지도/);
  });
});
