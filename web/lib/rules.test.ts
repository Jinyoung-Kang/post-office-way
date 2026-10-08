import { describe, expect, it } from "vitest";
import { careHoursText, rankText, worstFirst } from "./rules";
import { bboxParam, declutter, labelSize } from "./mapGeom";

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
});
