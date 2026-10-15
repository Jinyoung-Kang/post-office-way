// 지도 화면의 축소 한계와 이동 범위 — 카카오 타일에 그림이 있는 범위 밖(하늘색 띠·흰 바탕)이 보이지 않게. 지도 SDK 없이 숫자만 다룸.
// 좌표는 카카오 WCONGNAMUL(EPSG:5181 의 2.5배, 1 = 0.4m). 단계 L 에서 1px = 0.3125 × 2^L (단계 13 → 2560 ≈ 1km)
export type Rect = { minX: number; maxX: number; minY: number; maxY: number };

/** 카카오 기본 지도 타일에 그림이 있는 범위 — 2026-10-15 브라우저로 잰 경계(단계 12·13·14 에서 같음)에서 2km(5,000) 안쪽.
 *  밖은 하늘색 띠(타일 격자 안)와 흰 바탕(격자 밖)이라, 넓은 창에서 멀리 보면 지도 끝이 잘려 보였음 */
export const TILE_EXTENT: Rect = { minX: -1_876_000, maxX: 3_076_000, minY: -545_000, maxY: 3_123_000 };
/** 전국 시군구 경계(울릉·독도·마라도 포함)를 감싸는 사각형 */
export const KOREA: Rect = { minX: -25_200, maxX: 1_580_800, minY: -105_200, maxY: 1_422_500 };
/** SDK 의 가장 먼 단계 */
export const MAX_LEVEL = 14;

export function unitsPerPx(level: number): number {
  return 0.3125 * 2 ** level;
}

const width = (r: Rect) => r.maxX - r.minX;
const height = (r: Rect) => r.maxY - r.minY;

/** w×h(px) 지도가 가장 멀리 볼 수 있는 단계 — 화면이 타일 범위 안에 드는 가장 먼 단계.
 *  다만 그 단계에서 전국이 다 들어가지 않으면 전국이 들어가는 단계까지는 허용(전국 보기가 먼저, 넘친 가장자리는 clampCenter 가 양쪽에 나눔) */
export function maxLevelFor(w: number, h: number): number {
  let edgeFree = 1;
  for (let L = MAX_LEVEL; L > 1; L--) {
    if (w * unitsPerPx(L) <= width(TILE_EXTENT) && h * unitsPerPx(L) <= height(TILE_EXTENT)) { edgeFree = L; break; }
  }
  let whole = MAX_LEVEL;
  for (let L = 1; L < MAX_LEVEL; L++) {
    if (width(KOREA) <= w * unitsPerPx(L) && height(KOREA) <= h * unitsPerPx(L)) { whole = L; break; }
  }
  return Math.max(edgeFree, whole);
}

/** 화면 중심 (x, y) 를 옮겨 w×h 화면이 타일 범위를 넘지 않게. 화면이 범위보다 큰 축은 범위 가운데(넘친 만큼을 양쪽에 고르게) */
export function clampCenter(x: number, y: number, w: number, h: number, level: number): [number, number] {
  const u = unitsPerPx(level);
  const axis = (v: number, half: number, lo: number, hi: number) =>
    hi - lo <= 2 * half ? (lo + hi) / 2 : Math.min(Math.max(v, lo + half), hi - half);
  return [axis(x, (w * u) / 2, TILE_EXTENT.minX, TILE_EXTENT.maxX), axis(y, (h * u) / 2, TILE_EXTENT.minY, TILE_EXTENT.maxY)];
}

/** 카카오 기본 지도 타일의 바다색(타일 팔레트에서 읽은 값 — 범위 밖 하늘색 띠도 같은 색) */
export const SEA_COLOR = "#a3d6eb";
const MASK_MARGIN = 3_000_000;              // 덮개가 범위 밖으로 뻗는 폭 — 4,000px 창이 단계 13 에서 범위를 넘는 폭(약 2.6M)보다 넓게
const FADE_STEPS = 8, FADE_STEP = 5_000;    // 범위 안쪽 16km(단계 13 에서 약 16px)를 8겹으로 점점 옅게 — 넓으면 1920px 창의 양끝 땅까지 흐려짐

export type MaskRing = { outer: Rect; hole: Rect; opacity: number };
const inset = (r: Rect, d: number): Rect => ({ minX: r.minX + d, maxX: r.maxX - d, minY: r.minY + d, maxY: r.maxY - d });

/** 타일 범위 밖 덮개 — 넓고 낮은 창처럼 전국을 보이려면 범위를 넘을 수밖에 없을 때 흰 바탕·하늘색 띠 대신 바다가, 잘린 땅 대신
 *  바다로 흐려지는 가장자리가 보이게. 첫 겹은 범위 바깥 전체(불투명), 나머지는 범위 안쪽 가장자리에서 안으로 갈수록 옅어짐 */
export function maskRings(): MaskRing[] {
  const rings: MaskRing[] = [{ outer: inset(TILE_EXTENT, -MASK_MARGIN), hole: TILE_EXTENT, opacity: 1 }];
  for (let i = 0; i < FADE_STEPS; i++) {
    rings.push({ outer: inset(TILE_EXTENT, i * FADE_STEP), hole: inset(TILE_EXTENT, (i + 1) * FADE_STEP), opacity: (FADE_STEPS - i) / (FADE_STEPS + 1) });
  }
  return rings;
}
