import { describe, expect, it } from "vitest";
import { cardRunOf, geojsonPathOf, mapQueryFrom, mapQueryOf, mapStateOf, queryMatches, regionPathOf, sameMapQuery } from "./mapQuery";

describe("지도 화면 주소 읽기", () => {
  it("이 화면이 쓰는 문자열 값만 꺼냄", () => {
    expect(mapQueryFrom({ adm: "47190", metric: "FAR2KM_SHARE", in: undefined, other: "x" }))
      .toEqual({ adm: "47190", metric: "FAR2KM_SHARE" });
    expect(mapQueryFrom({ adm: ["1", "2"], in: "47" })).toEqual({ in: "47" });
  });

  it("시군구 지역(5자리) → 시군구 단위로 선택·확대", () => {
    expect(mapStateOf({ adm: "47190", metric: "FAR2KM_SHARE" })).toEqual({
      metric: "FAR2KM_SHARE", level: 2, parent: "", selected: "47190", focus: "47190" });
  });

  it("읍면동 지역 → 그 시군구의 읍면동 단위로", () => {
    expect(mapStateOf({ adm: "4711155" })).toEqual({ level: 3, parent: "47111", selected: "4711155", focus: "4711155" });
  });

  it("in 만 있으면 그 범위의 읍면동을 선택 없이", () => {
    expect(mapStateOf({ in: "47" })).toEqual({ level: 3, parent: "47", selected: null, focus: null });
  });

  it("빈 값은 반영하지 않음", () => {
    expect(mapStateOf({ adm: "", metric: "", in: "" })).toEqual({});
  });

  it("비교 — 같은 값인지, 주소에 그대로 있는지", () => {
    expect(sameMapQuery({ adm: "47190" }, { adm: "47190" })).toBe(true);
    expect(sameMapQuery({ adm: "47190" }, { adm: "47190", in: "47" })).toBe(false);
    expect(queryMatches({ adm: "47190" }, { adm: "47190" })).toBe(true);
    expect(queryMatches({ adm: ["47190"] }, { adm: "47190" })).toBe(false);
    expect(queryMatches({}, {})).toBe(true);
  });
});

describe("지도 화면 주소 쓰기", () => {
  const base = { metric: "ACCESS_GAP_SCORE", level: 2 as const, parent: "", selected: null };

  it("기본 지표·선택 없음이면 빈 주소", () => {
    expect(mapQueryOf(base)).toEqual({});
  });

  it("지표와 선택 지역", () => {
    expect(mapQueryOf({ ...base, metric: "FAR2KM_SHARE", selected: "47190" })).toEqual({ metric: "FAR2KM_SHARE", adm: "47190" });
    expect(Object.keys(mapQueryOf({ ...base, metric: "FAR2KM_SHARE", selected: "47190" }))).toEqual(["metric", "adm"]);
  });

  it("읍면동 단위의 범위는 in, 읍면동을 고르면 adm 만", () => {
    expect(mapQueryOf({ ...base, level: 3, parent: "47" })).toEqual({ in: "47" });
    expect(mapQueryOf({ ...base, level: 3, parent: "47111", selected: "4711155" })).toEqual({ adm: "4711155" });
  });
});

describe("단계구분도 경로", () => {
  it("시군구 · 전국", () => {
    expect(geojsonPathOf({ metric: "ACCESS_GAP_SCORE", level: 2, parent: "" }, true))
      .toBe("/areas/geojson?level=2&metric=ACCESS_GAP_SCORE");
  });

  it("읍면동은 상위 지역이 있어야 요청", () => {
    expect(geojsonPathOf({ metric: "FAR2KM_SHARE", level: 3, parent: "47" }, true))
      .toBe("/areas/geojson?level=3&metric=FAR2KM_SHARE&parent=47");
    expect(geojsonPathOf({ metric: "FAR2KM_SHARE", level: 3, parent: "" }, true)).toBeNull();
  });

  it("주소를 읽기 전에는 요청하지 않고, 읽은 뒤에는 주소의 지표로 한 번", () => {
    // ?adm=47190&metric=FAR2KM_SHARE 첫 렌더: 상태는 아직 기본값 — 기본 지표 전국 GeoJSON 을 받으면 안 됨
    expect(geojsonPathOf({ metric: "ACCESS_GAP_SCORE", level: 2, parent: "" }, false)).toBeNull();
    const s = { metric: "ACCESS_GAP_SCORE", level: 2 as const, parent: "", selected: null, focus: null,
      ...mapStateOf({ adm: "47190", metric: "FAR2KM_SHARE" }) };
    expect(geojsonPathOf(s, true)).toBe("/areas/geojson?level=2&metric=FAR2KM_SHARE");
  });
});

describe("지역 카드 경로", () => {
  it("지도 자료가 오기 전에는 요청하지 않음 — 계산 실행 없이 한 번, 붙여서 또 한 번 받지 않게", () => {
    expect(cardRunOf(null, false)).toBeNull();
    expect(regionPathOf("47190", cardRunOf(null, false))).toBeNull();
    const fc = { meta: { calcRunId: "c-1" } };
    expect(regionPathOf("47190", cardRunOf(fc, false))).toBe("/areas/47190?calcRunId=c-1");
  });

  it("지도 자료를 못 받았으면 최신 계산 실행으로", () => {
    expect(cardRunOf(null, true)).toBeUndefined();
    expect(regionPathOf("47190", cardRunOf(null, true))).toBe("/areas/47190");
  });
});
