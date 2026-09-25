import { describe, expect, it } from "vitest";
import { classOf, dist, groupMetrics, num, quantileBreaks, SEQ, shortSido, withUnit } from "./format";

describe("quantileBreaks", () => {
  it("값이 고르게 퍼지면 단계 수 - 1 개의 경계", () => {
    const b = quantileBreaks(Array.from({ length: 100 }, (_, i) => i));
    expect(b).toEqual([20, 40, 60, 80]);
    expect(classOf(0, b)).toBe(0);
    expect(classOf(99, b)).toBe(SEQ.length - 1);
  });

  it("0 이 몰린 공백 인구 지표는 0 을 첫 단계로 따로 두고 나머지로 분위수", () => {
    const vals = [...Array(70).fill(0), ...Array.from({ length: 30 }, (_, i) => (i + 1) * 10)];
    const b = quantileBreaks(vals);
    expect(b[0]).toBe(10);                     // 0 만 첫 단계
    expect(b.length).toBeGreaterThanOrEqual(3); // '미만/이상' 두 단계로 뭉개지지 않음
    expect(classOf(0, b)).toBe(0);
    expect(classOf(10, b)).toBeGreaterThan(0);
  });

  it("모두 같은 값이거나 비어 있으면 경계 없음", () => {
    expect(quantileBreaks([5, 5, 5])).toEqual([]);
    expect(quantileBreaks([])).toEqual([]);
  });

  it("값 없음은 -1 단계", () => {
    expect(classOf(null, [1, 2])).toBe(-1);
  });
});

describe("표기", () => {
  it("거리·단위", () => {
    expect(dist(950)).toBe("950 m");
    expect(dist(1234)).toBe("1.23 km");
    expect(dist(null)).toBe("—");
    expect(withUnit(12.345, "%")).toBe("12.3%");
    expect(withUnit(1, "0/1")).toBe("있음");
    expect(num(1234567)).toBe("1,234,567");
  });

  it("시도 약칭", () => {
    expect(shortSido("경상북도")).toBe("경북");
    expect(shortSido("서울특별시")).toBe("서울");
    expect(shortSido("강원특별자치도")).toBe("강원");
    expect(shortSido(null)).toBe("");
  });
});

describe("groupMetrics", () => {
  it("주제 순서대로 묶고 모르는 코드는 기타", () => {
    const g = groupMetrics([{ code: "POST_SOLE_HUB_PPLTN" }, { code: "NEAREST_FIN_DIST_M" }, { code: "NEW_ONE" }]);
    expect(g.map((x) => x.label)).toEqual(["우체국 거리", "생활 거점", "기타"]);
  });
});
