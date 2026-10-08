// 지도 기하 — 화면 범위 문자열, 늘 보이는 라벨의 크기 추정과 겹침 거르기. 지도 SDK 없이 숫자만 다룸
export type Box = { x: number; y: number; w: number; h: number };

/** API bbox 인자 'minLon,minLat,maxLon,maxLat' (소수 5자리 ≈ 1m — 같은 화면이면 같은 문자열이라 캐시가 맞음) */
export function bboxParam(minLon: number, minLat: number, maxLon: number, maxLat: number): string {
  return [minLon, minLat, maxLon, maxLat].map((v) => v.toFixed(5)).join(",");
}

/** 라벨 화면 크기 추정 — 글자 수 × 약 7px + 여백 (겹침 판정용, 실제 그리기 전) */
export function labelSize(title: string, value?: string): { w: number; h: number } {
  return { w: (title.length + (value?.length || 0)) * 7 + 28, h: 22 };
}

/** 우선순위(배열 순서)대로 놓으며 앞의 것과 겹치는 상자는 숨김 → 보일지 여부. 간격 gapX·gapY 안이면 겹침으로 봄 */
export function declutter(boxes: Box[], gapX = 4, gapY = 2): boolean[] {
  const kept: Box[] = [];
  return boxes.map((b) => {
    const hit = kept.some((k) => b.x < k.x + k.w + gapX && k.x < b.x + b.w + gapX && b.y < k.y + k.h + gapY && k.y < b.y + b.h + gapY);
    if (!hit) kept.push(b);
    return !hit;
  });
}

