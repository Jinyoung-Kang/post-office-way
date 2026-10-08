import { describe, expect, it } from "vitest";
import { dist, groupMetrics, localStamp, num, sentences, shortSido, walkMin, withUnit } from "./format";

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

it("localStamp", () => {
  expect(localStamp(new Date(2026, 9, 8, 7, 5, 3))).toBe("2026-10-08 07:05:03");
});

