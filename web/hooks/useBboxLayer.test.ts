// 지도 레이어 점의 clickable — 점마다 정할 수 있어야 누를 수 없는 점(새마을금고·저축은행)이 지도 클릭을 막지 않음
import { describe, expect, it } from "vitest";
import { isClickable } from "./useBboxLayer";

describe("isClickable", () => {
  it("불리언은 그대로, 함수면 점마다", () => {
    expect(isClickable(true, { id: 1 })).toBe(true);
    expect(isClickable(undefined, { id: 1 })).toBe(false);
    const evaluable = (b: { brand: string }) => b.brand !== "새마을금고";
    expect(isClickable(evaluable, { brand: "KB국민은행" })).toBe(true);
    expect(isClickable(evaluable, { brand: "새마을금고" })).toBe(false);
  });
});
