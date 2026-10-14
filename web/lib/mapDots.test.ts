// 지도 레이어 점(DOM) — document.createElement 를 흉내 내 속성·이벤트를 확인
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Bank, CarePlace, Facility } from "./api";
import { bankDot, careDot, facilityDot } from "./mapDots";

type FakeEl = {
  tagName: string; className: string; title: string; tabIndex: number; style: Record<string, string>;
  attrs: Record<string, string>; on: Record<string, ((e: unknown) => void)[]>;
  setAttribute: (k: string, v: string) => void; addEventListener: (t: string, f: (e: unknown) => void) => void;
};

function fakeEl(tag: string): FakeEl {
  const el: FakeEl = {
    tagName: tag.toUpperCase(), className: "", title: "", tabIndex: -1, style: {}, attrs: {}, on: {},
    setAttribute: (k, v) => { el.attrs[k] = v; },
    addEventListener: (t, f) => { (el.on[t] ??= []).push(f); },
  };
  return el;
}

// 이벤트 흉내 — 막았는지(preventDefault·stopPropagation) 기록
function ev(extra: Record<string, unknown> = {}) {
  const e = { prevented: false, stopped: false, preventDefault() { e.prevented = true; }, stopPropagation() { e.stopped = true; }, ...extra };
  return e;
}
const fire = (el: FakeEl, type: string, e: unknown) => (el.on[type] ?? []).forEach((f) => f(e));

beforeEach(() => { vi.stubGlobal("document", { createElement: (t: string) => fakeEl(t) }); });
afterEach(() => { vi.unstubAllGlobals(); });

const fac = { histId: 1, name: "광화문우체국", divLabel: "우체국", finAvailable: true, postDiv: 1 } as Facility;
const bank = { placeId: "p1", name: "국민은행 광화문지점", brand: "국민은행", category: "금융 > 은행", kind: "BRANCH" } as Bank;
const coop = { placeId: "p2", name: "새마을금고 종로", brand: "새마을금고", category: "금융 > 새마을금고", kind: "BRANCH" } as Bank;

describe("시설 점", () => {
  it("색·제목, 누를 수 있는 단추(초점·이름)", () => {
    const el = facilityDot(fac, () => undefined) as unknown as FakeEl;
    expect(el.className).toBe("fac-dot");
    expect(el.style.background).toBe("#ff9500");
    expect(el.title).toBe("광화문우체국 (우체국)");
    expect(el.attrs).toEqual({ role: "button", "aria-label": "광화문우체국 우체국" });
    expect(el.tabIndex).toBe(0);
  });

  it("클릭·Enter·Space 로 고르고, 다른 키는 무시", () => {
    const pick = vi.fn();
    const el = facilityDot(fac, pick) as unknown as FakeEl;
    const c = ev(); fire(el, "click", c);
    expect(c.stopped).toBe(true);
    for (const key of ["Enter", " "]) {
      const k = ev({ key }); fire(el, "keydown", k);
      expect(k.prevented).toBe(true);
    }
    fire(el, "keydown", ev({ key: "a" }));
    expect(pick).toHaveBeenCalledTimes(3);
    expect(pick).toHaveBeenCalledWith(fac);
  });

  it("365코너·기타 시설 색", () => {
    expect((facilityDot({ ...fac, finAvailable: false, postDiv: 3 }, () => undefined) as unknown as FakeEl).style.background).toBe("#34c759");
    expect((facilityDot({ ...fac, finAvailable: false, postDiv: 2 }, () => undefined) as unknown as FakeEl).style.background).toBe("#8e8e93");
  });
});

describe("은행 지점 점", () => {
  it("영향평가 대상 은행은 눌러서 고름 — 제목에 안내", () => {
    const pick = vi.fn();
    const el = bankDot(bank, pick) as unknown as FakeEl;
    expect(el.className).toBe("fac-dot");
    expect(el.style).toMatchObject({ background: "#af52de", borderRadius: "3px", cursor: "pointer" });
    expect(el.title).toBe("국민은행 광화문지점 · 국민은행 — 눌러서 문을 닫으면 영향 보기");
    const c = ev(); fire(el, "click", c);
    expect(c.stopped).toBe(true);
    expect(pick).toHaveBeenCalledWith(bank);
  });

  it("새마을금고처럼 대상이 아니면 누를 수 없음", () => {
    const el = bankDot(coop, vi.fn()) as unknown as FakeEl;
    expect(el.title).toBe("새마을금고 종로 · 새마을금고");
    expect(el.style.cursor).toBeUndefined();
    expect(el.on.click).toBeUndefined();
  });
});

describe("약국·의원 점", () => {
  it("색·제목에 진료시간", () => {
    const p = { id: "c1", kind: "PHARMACY", name: "온누리약국", divName: "약국", hours: {} } as unknown as CarePlace;
    const el = careDot(p) as unknown as FakeEl;
    expect(el.className).toBe("care-dot");
    expect(el.style.background).toBe("#30b0c7");
    expect(el.title).toBe("온누리약국 (약국)");
  });
});
