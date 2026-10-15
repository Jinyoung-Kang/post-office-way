import { describe, expect, it } from "vitest";
import { clampCenter, KOREA, maskRings, MAX_LEVEL, maxLevelFor, TILE_EXTENT, unitsPerPx, type Rect } from "./mapView";

const width = (r: Rect) => r.maxX - r.minX;
const height = (r: Rect) => r.maxY - r.minY;
// 중심 (x, y)·크기 w×h·단계 level 인 화면이 덮는 범위
const viewOf = (x: number, y: number, w: number, h: number, level: number): Rect => {
  const u = unitsPerPx(level);
  return { minX: x - (w * u) / 2, maxX: x + (w * u) / 2, minY: y - (h * u) / 2, maxY: y + (h * u) / 2 };
};
const inside = (v: Rect, r: Rect) => v.minX >= r.minX && v.maxX <= r.maxX && v.minY >= r.minY && v.maxY <= r.maxY;

describe("축소 단계의 해상도", () => {
  it("단계마다 두 배 — 13 은 1px 에 2560(약 1km)", () => {
    expect(unitsPerPx(12)).toBe(1280);
    expect(unitsPerPx(13)).toBe(2560);
    expect(unitsPerPx(14)).toBe(5120);
  });
});

describe("가장 멀리 볼 수 있는 단계", () => {
  it("넓은 창(2548×1205) — 13 이면 타일 범위 밖이 보여 12 까지만, 12 에서도 전국이 다 들어감", () => {
    // 사용자 화면: 단계 13 으로 맞춰져 왼쪽·오른쪽·아래에 하늘색 띠와 흰 바탕이 보였음
    expect(maxLevelFor(2548, 1205)).toBe(12);
    expect(width(KOREA) / unitsPerPx(12)).toBeLessThanOrEqual(2548);
    expect(height(KOREA) / unitsPerPx(12)).toBeLessThanOrEqual(1205);
  });

  it("노트북 창(1024×716) — 전국이 13 에 들어가므로 14(범위 밖이 보임)로는 줄이지 않음", () => {
    expect(maxLevelFor(1024, 716)).toBe(13);
  });

  it("12 에서 전국이 잘리는 창(2000×950)은 범위를 조금 넘더라도 13 까지 — 전국 보기가 먼저", () => {
    expect(height(KOREA) / unitsPerPx(12)).toBeGreaterThan(950);
    expect(maxLevelFor(2000, 950)).toBe(13);
  });

  it("휴대폰(375×650)은 전국이 들어가는 14 까지, 아주 넓은 창(3440×1390)은 12", () => {
    expect(maxLevelFor(375, 650)).toBe(MAX_LEVEL);
    expect(maxLevelFor(3440, 1390)).toBe(12);
  });

  it("크기를 아직 모르면(0) 제한하지 않음", () => {
    expect(maxLevelFor(0, 0)).toBe(MAX_LEVEL);
  });

  it("여러 창 크기에서 — 가장 먼 단계에서도 전국이 들어가고, 범위를 넘는 것은 한 단계 가까이에서 전국이 잘릴 때뿐", () => {
    for (let w = 320; w <= 3840; w += 160) {
      for (let h = 480; h <= 2160; h += 120) {
        const L = maxLevelFor(w, h);
        const u = unitsPerPx(L);
        expect(width(KOREA) <= w * u && height(KOREA) <= h * u || L === MAX_LEVEL).toBe(true);
        const overflows = w * u > width(TILE_EXTENT) || h * u > height(TILE_EXTENT);
        if (overflows) {
          const closer = unitsPerPx(L - 1);
          expect(width(KOREA) <= w * closer && height(KOREA) <= h * closer).toBe(false);
        }
      }
    }
  });
});

describe("화면 중심을 타일 범위 안으로", () => {
  const center = { x: (KOREA.minX + KOREA.maxX) / 2, y: (KOREA.minY + KOREA.maxY) / 2 };

  it("범위 안이면 그대로", () => {
    expect(clampCenter(center.x, center.y, 1024, 716, 13)).toEqual([center.x, center.y]);
  });

  it("왼쪽 위로 끌어 범위를 넘으면 그 가장자리에 붙임", () => {
    const [x, y] = clampCenter(TILE_EXTENT.minX, TILE_EXTENT.maxY, 1024, 716, 13);
    const v = viewOf(x, y, 1024, 716, 13);
    expect(v.minX).toBeCloseTo(TILE_EXTENT.minX);
    expect(v.maxY).toBeCloseTo(TILE_EXTENT.maxY);
    expect(inside(v, TILE_EXTENT)).toBe(true);
  });

  it("화면이 범위보다 넓은 축은 범위 가운데 — 넘친 만큼이 양쪽에 고르게. 다른 축은 범위 안으로", () => {
    const [x, y] = clampCenter(center.x, center.y, 2000, 950, 13);
    expect(x).toBe((TILE_EXTENT.minX + TILE_EXTENT.maxX) / 2);
    const v = viewOf(x, y, 2000, 950, 13);
    expect(v.minY).toBeGreaterThanOrEqual(TILE_EXTENT.minY);
    expect(v.maxY).toBeLessThanOrEqual(TILE_EXTENT.maxY);
  });

  it("넓은 창의 첫 화면(2548×1205, 단계 12)은 전국 가운데에서도 범위 안", () => {
    const [x, y] = clampCenter(center.x, center.y, 2548, 1205, maxLevelFor(2548, 1205));
    expect(inside(viewOf(x, y, 2548, 1205, 12), TILE_EXTENT)).toBe(true);
  });
});

describe("타일 범위 밖 덮개", () => {
  const rings = maskRings();
  const extentCenter = { x: (TILE_EXTENT.minX + TILE_EXTENT.maxX) / 2, y: (TILE_EXTENT.minY + TILE_EXTENT.maxY) / 2 };

  it("첫 겹은 범위 바깥 전체를 불투명하게 — 아주 넓은 창(3840×2160)이 단계 13 에서 넘는 곳까지", () => {
    expect(rings[0].opacity).toBe(1);
    expect(rings[0].hole).toEqual(TILE_EXTENT);
    expect(inside(viewOf(extentCenter.x, extentCenter.y, 3840, 2160, 13), rings[0].outer)).toBe(true);
  });

  it("나머지 겹은 범위 안쪽 가장자리에서 빈틈 없이 이어지며 점점 옅어짐", () => {
    for (let i = 1; i < rings.length; i++) {
      expect(rings[i].outer).toEqual(rings[i - 1].hole);
      expect(rings[i].opacity).toBeLessThan(rings[i - 1].opacity);
      expect(rings[i].opacity).toBeGreaterThan(0);
      expect(inside(rings[i].outer, TILE_EXTENT)).toBe(true);
    }
  });

  it("흐려지는 띠는 전국 근처에 닿지 않음(가장 안쪽 구멍이 전국을 넉넉히 감쌈)", () => {
    const hole = rings[rings.length - 1].hole;
    expect(inside(KOREA, hole)).toBe(true);
    expect(KOREA.minX - hole.minX).toBeGreaterThan(1_000_000);
  });
});
