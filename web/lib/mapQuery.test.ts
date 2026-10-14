import { describe, expect, it } from "vitest";
import { cardRunOf, geojsonPathOf, MAP_DEFAULTS, mapQueryFrom, mapQueryOf, mapStateOf, queryMatches, regionPathOf, sameMapQuery } from "./mapQuery";

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
    expect(mapStateOf({ adm: "4711155" })).toEqual(
      { metric: "ACCESS_GAP_SCORE", level: 3, parent: "47111", selected: "4711155", focus: "4711155" });
  });

  it("in 만 있으면 그 범위의 읍면동을 선택 없이", () => {
    expect(mapStateOf({ in: "47" })).toEqual({ metric: "ACCESS_GAP_SCORE", level: 3, parent: "47", selected: null, focus: null });
  });

  it("주소에 없는 값은 기본값 — 파라미터 없는 '/'(머리글 링크)로 오면 처음 화면으로", () => {
    expect(mapStateOf({})).toEqual(MAP_DEFAULTS);
    expect(MAP_DEFAULTS).toEqual({ metric: "ACCESS_GAP_SCORE", level: 2, parent: "", selected: null, focus: null });
    expect(mapStateOf({ adm: "", metric: "", in: "" })).toEqual(MAP_DEFAULTS);
    expect(mapStateOf({ metric: "FAR2KM_SHARE" })).toEqual({ ...MAP_DEFAULTS, metric: "FAR2KM_SHARE" });
  });

  it("읍면동을 고른 채 시도 전체를 보던 주소(?adm=읍면동&in=시도)는 시도 전체로", () => {
    expect(mapStateOf({ adm: "4711155", in: "47" })).toEqual(
      { metric: "ACCESS_GAP_SCORE", level: 3, parent: "47", selected: "4711155", focus: "4711155" });
    expect(mapStateOf({ adm: "4711155", in: "11" }).parent).toBe("47111");     // 그 지역을 품지 않는 범위는 무시
    expect(mapStateOf({ adm: "47190", in: "47" })).toMatchObject({ level: 2, parent: "" });   // 시군구 단위는 in 을 쓰지 않음
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

  it("시도 전체를 보며 읍면동을 고르면 in 도 남김 — 새로고침해도 시도 전체", () => {
    expect(mapQueryOf({ ...base, level: 3, parent: "47", selected: "4711155" })).toEqual({ adm: "4711155", in: "47" });
  });

  it("주소로 쓰고 다시 읽으면 같은 화면", () => {
    const states = [
      { ...MAP_DEFAULTS },
      { metric: "FAR2KM_SHARE", level: 2 as const, parent: "", selected: "47190", focus: "47190" },
      { metric: "FAR2KM_SHARE", level: 3 as const, parent: "47", selected: "4711155", focus: "4711155" },
      { metric: "ACCESS_GAP_SCORE", level: 3 as const, parent: "47111", selected: "4711155", focus: "4711155" },
      { metric: "ACCESS_GAP_SCORE", level: 3 as const, parent: "47", selected: null, focus: null },
    ];
    for (const s of states) expect(mapStateOf(mapQueryOf(s))).toEqual(s);
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
    expect(geojsonPathOf(mapStateOf({ adm: "47190", metric: "FAR2KM_SHARE" }), true)).toBe("/areas/geojson?level=2&metric=FAR2KM_SHARE");
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
