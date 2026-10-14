import { describe, expect, it } from "vitest";
import type { Region } from "./api";
import { emdNeed, NO_EMD_TEXT, regionsErrorText, regionsOf } from "./regions";

const r = (admCd: string, emdCount: number): Region =>
  ({ admCd, admNm: admCd, sigunguCount: 1, emdCount, sigungu: [{ admCd: `${admCd}110`, admNm: "구" }] });

describe("시도 목록 (/meta/regions)", () => {
  it("받는 중 — 목록은 비고 오류 없음", () => {
    const v = regionsOf({ data: null, error: null, loading: true });
    expect(v).toEqual({ items: [], error: null, loading: true, emdAvailable: [] });
    expect(emdNeed(v)).toBe("loading");
  });

  it("실패를 빈 목록으로 삼키지 않고 오류를 함께 돌려줌", () => {
    const e = new Error("점검용 실패");
    const v = regionsOf({ data: null, error: e, loading: false });
    expect(v.items).toEqual([]);
    expect(v.error).toBe(e);
    expect(v.loading).toBe(false);
    expect(emdNeed(v)).toBe("error");
    expect(regionsErrorText(e)).toContain("점검용 실패");
    expect(regionsErrorText(e)).toContain("시도 목록");
  });

  it("읍면동 자료가 있는 시도만 골라 둠", () => {
    const v = regionsOf({ data: { items: [r("11", 0), r("47", 300)] }, error: null, loading: false });
    expect(v.emdAvailable.map((x) => x.admCd)).toEqual(["47"]);
    expect(emdNeed(v)).toBe("ok");
  });

  it("받았는데 읍면동 자료가 있는 시도가 없으면 끝없는 자리 표시 대신 빈 상태", () => {
    const v = regionsOf({ data: { items: [r("11", 0)] }, error: null, loading: false });
    expect(emdNeed(v)).toBe("none");
    expect(NO_EMD_TEXT).toMatch(/읍면동/);
  });
});
