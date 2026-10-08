import { describe, expect, it } from "vitest";
import { classOf, fixedClass, legendRows, minOnlyValue, quantileBreaks, SEQ } from "./choropleth";

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

describe("범례·고정 경계", () => {
  it("범례 — 0/1, 같은 값, 미만·구간·이상, 최솟값 하나뿐인 첫 단계", () => {
    expect(legendRows([], "명", true).map((r) => r.label)).toEqual(["없음", "있음"]);
    expect(legendRows([], "명", false)).toEqual([{ label: "모든 지역 같은 값", color: SEQ[0] }]);
    const rows = legendRows([10, 20, 30, 40], "명", false);
    expect(rows.map((r) => r.label)).toEqual(["10명 미만", "10명 – 20명", "20명 – 30명", "30명 – 40명", "40명 이상"]);
    expect(rows.map((r) => r.color)).toEqual(SEQ);
    expect(legendRows([10, 20], "명", false, 0)[0].label).toBe("0명");
  });

  it("첫 단계가 최솟값 하나뿐일 때만 그 값", () => {
    expect(minOnlyValue([0, 0, 10, 20, 30], [10, 20])).toBe(0);
    expect(minOnlyValue([0, 5, 10, 20], [10, 20])).toBeNull();    // 첫 단계에 0 과 5 가 섞임
    expect(minOnlyValue([], [10])).toBeNull();
  });

  it("고정 경계 단계", () => {
    expect(fixedClass(null, [10, 25])).toBe(-1);
    expect([0, 10, 24.9, 25, 99].map((v) => fixedClass(v, [10, 25]))).toEqual([0, 1, 1, 2, 2]);
  });
});
