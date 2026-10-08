import { describe, expect, it } from "vitest";
import { classOf, dist, groupMetrics, num, quantileBreaks, sentences, SEQ, shortSido, walkMin, withUnit } from "./format";

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
    expect(withUnit(7425.5, "명")).toBe("7,426명");          // 사람 수는 정수 (중앙값이 x.5 여도)
  });

  it("걷는 시간 — 고령자 0.8m/s", () => {
    expect(walkMin(1440)).toBe("30분");
    expect(walkMin(10)).toBe("1분");                         // 0분으로 보이지 않게
    expect(walkMin(null)).toBe("—");
    expect(walkMin(Infinity)).toBe("—");
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

describe("sentences", () => {
  it("마침표 뒤 공백에서만 나눔 — 숫자 속 점·괄호는 그대로", () => {
    expect(sentences("집계구(평균 약 500명)마다 판정합니다. 0.8m/s 로 걷습니다.")).toEqual(["집계구(평균 약 500명)마다 판정합니다.", "0.8m/s 로 걷습니다."]);
    expect(sentences("한 문장입니다.")).toEqual(["한 문장입니다."]);
    expect(sentences("2026년 개정된 절차를 참고합니다. 분석용입니다. ")).toHaveLength(2);
    expect(sentences("같은 범위 안에서 0~100. 순위 비교용")).toEqual(["같은 범위 안에서 0~100.", "순위 비교용"]);
  });

  it("순번·날짜 표기는 나누지 않음", () => {
    expect(sentences("1. 광화문우체국")).toEqual(["1. 광화문우체국"]);
    expect(sentences("자료 2026. 09. 25. 오후 02:41 기준")).toHaveLength(1);
  });
});

describe("유한하지 않은 값", () => {
  it("NaN·Infinity 는 '—' — 0 으로 나눈 비율 등이 '∞'·'— m'·'없음' 으로 보이지 않게", () => {
    expect(num(Infinity)).toBe("—");
    expect(num(-Infinity, 1)).toBe("—");
    expect(dist(NaN)).toBe("—");
    expect(dist(Infinity)).toBe("—");
    expect(withUnit(NaN, "0/1")).toBe("—");
    expect(withUnit(Infinity, "명")).toBe("—");
    expect(withUnit(NaN, "%")).toBe("—");
  });
});

