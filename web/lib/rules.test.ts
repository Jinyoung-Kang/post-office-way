import { describe, expect, it } from "vitest";
import { careHoursText, isBankEvaluable, missingAtLevel, netOutWarn, rankText, shadeText, sideText, topText, worstFirst } from "./rules";
import { bboxParam, declutter, diffKeys, labelSize } from "./mapGeom";

describe("화면 규칙", () => {
  const areas = [{ id: "a", value: 5, lat: 1, lon: 1 }, { id: "b", value: 9, lat: 1, lon: 1 },
    { id: "c", value: null, lat: 1, lon: 1 }, { id: "d", value: 7, lat: null, lon: 1 }, { id: "e", value: 1, lat: 1, lon: 1 }];
  it("취약한 쪽부터 — 값·좌표 없는 지역 제외", () => {
    expect(worstFirst(areas, true, 2).map((x) => x.id)).toEqual(["b", "a"]);
    expect(worstFirst(areas, false, 2).map((x) => x.id)).toEqual(["e", "a"]);
  });
  it("순위 문구", () => {
    expect(rankText({ rank: 3, rankOf: 250, higherIsWorse: true }, String)).toBe("나쁜 쪽에서 3번째");
    expect(rankText({ rank: 3, rankOf: 250, higherIsWorse: false }, String)).toBe("큰 쪽에서 3번째");
    expect(rankText({ rank: null, rankOf: 250, higherIsWorse: true }, String)).toBe("—");
  });
  it("인구 추세 지표는 유출·유입 쪽으로 읽음", () => {
    expect(rankText({ rank: 2, rankOf: 229, higherIsWorse: true, code: "NET_OUT_12M_PER_1K" }, String)).toBe("유출 많은 쪽에서 2번째");
    expect(rankText({ rank: 2, rankOf: 229, higherIsWorse: true, code: "POPW_FIN_DIST_M" }, String)).toBe("나쁜 쪽에서 2번째");
    expect(sideText("NET_OUT_12M_PER_1K", true, true)).toBe("유출 많은 쪽");
    expect(sideText("NET_OUT_12M_PER_1K", true, false)).toBe("유입 많은 쪽");
    expect(sideText("AGED65_NET_IN_12M_PER_1K", false, true)).toBe("65세 이상 유입 많은 쪽");
    expect(sideText("POPW_FIN_DIST_M", true, true)).toBe("접근성 취약 쪽");
    expect(sideText("FAC_CNT_R2KM", false, true)).toBe("접근성 양호 쪽");
    expect(topText("AGED65_NET_IN_12M_PER_1K", false)).toBe("65세 이상 유출 많은 8곳 표시");   // worstFirst(false) = 작은 쪽
    expect(topText("NET_OUT_12M_PER_1K", true)).toBe("유출 많은 8곳 표시");
    expect(topText("FAC_CNT_R2KM", false)).toBe("값이 작은 8곳 표시");
    expect(shadeText("NET_OUT_12M_PER_1K", true)).toContain("나간 사람");
    expect(shadeText("POPW_FIN_DIST_M", true)).toBe("진할수록 접근성이 취약한 쪽입니다.");
  });
  it("단위에 값이 없는 지표", () => {
    expect(missingAtLevel({ levels: [2] }, 3)).toBe(true);
    expect(missingAtLevel({ levels: [2, 3] }, 3)).toBe(false);
    expect(missingAtLevel({ levels: [] }, 3)).toBe(false);          // 값이 아직 없는 지표는 목록에서 이미 빠짐
    expect(missingAtLevel(undefined, 3)).toBe(false);
  });
  it("순유출 경고 — 백분위 80 이상", () => {
    expect([netOutWarn(80), netOutWarn(79.9), netOutWarn(null), netOutWarn(undefined)]).toEqual([true, false, false, false]);
  });
  it("은행 지점 영향평가 대상", () => {
    expect(isBankEvaluable({ kind: "BRANCH", brand: "KB국민은행" })).toBe(true);
    expect(isBankEvaluable({ kind: "BRANCH", brand: "새마을금고" })).toBe(false);
    expect(isBankEvaluable({ kind: "BRANCH", brand: "저축은행" })).toBe(false);
    expect(isBankEvaluable({ kind: "ATM", brand: "KB국민은행" })).toBe(false);
    expect(isBankEvaluable({ kind: "BRANCH", brand: null })).toBe(false);
  });
  it("진료시간 — 월·토·일·공휴일만", () => {
    expect(careHoursText({ "1": ["0900", "1800"], "2": ["0900", "1800"], "6": ["0900", "1300"], "8": ["1000", "1500"] }))
      .toBe("월 09:00~18:00 · 토 09:00~13:00 · 공휴일 10:00~15:00");
    expect(careHoursText(null)).toBe("");
  });
});

describe("지도 기하", () => {
  it("bbox 문자열", () => { expect(bboxParam(127.123456, 37.5, 127.2, 37.654321)).toBe("127.12346,37.50000,127.20000,37.65432"); });
  it("라벨 크기 추정 — 글자 5 + 7", () => { expect(labelSize("1 의성군", "12.3 km")).toEqual({ w: (5 + 7) * 7 + 28, h: 22 }); });
  it("겹치면 뒤의(우선순위 낮은) 라벨을 숨김", () => {
    const boxes = [{ x: 0, y: 0, w: 50, h: 20 }, { x: 40, y: 5, w: 50, h: 20 }, { x: 200, y: 0, w: 50, h: 20 },
      { x: 52, y: 0, w: 10, h: 10 }];   // 첫 상자와 4px 간격 안 → 겹침
    expect(declutter(boxes)).toEqual([true, false, true, false]);
  });
  it("레이어 갱신 — 화면 밖으로 나간 것만 지우고 새로 들어온 것만 만듦", () => {
    expect(diffKeys(["a", "b", "c"], ["b", "c", "d"])).toEqual({ remove: ["a"], add: ["d"] });
    expect(diffKeys([], ["x"])).toEqual({ remove: [], add: ["x"] });
    expect(diffKeys(["x"], ["x"])).toEqual({ remove: [], add: [] });
  });
});
