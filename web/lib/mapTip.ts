// 지도 말풍선·라벨 HTML — 카카오 오버레이는 HTML 문자열을 받으므로, 화면에 넣는 모든 글자는 여기서 한 번에 이스케이프.
// 예전에는 페이지마다 HTML 문자열을 직접 만들어 지표명·단위·사유 문구가 이스케이프 없이 들어갔음 (리뷰 S4)

export type TipPart = string | { b: string };   // 문자열 = 보통 글자, { b } = 굵게
export type TipLines = TipPart[][];             // 줄 목록

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

export function tipHtml(title: string, lines: TipLines, pinned = false): string {
  const body = lines.map((line) => line.map((p) => (typeof p === "string" ? esc(p) : `<b>${esc(p.b)}</b>`)).join(""))
    .filter(Boolean).join("<br/>");
  return `<div class="map-tip">${pinned ? '<span class="map-tip-x" aria-hidden="true">✕</span>' : ""}` +
    `<b>${esc(title)}</b>${body ? `<br/>${body}` : ""}</div>`;
}

/** 말풍선과 가리킨 점 사이 간격(px) — 아래로 둘 때는 마우스 포인터에 가리지 않게 더 띄움 */
export const TIP_GAP = { above: 14, below: 20 };

type Size = { w: number; h: number };

/** 말풍선 왼쪽 위 위치(지도 컨테이너 기준 px). 기본은 가리킨 점 (x, y) 위 가운데.
 *  지도 끝이나 떠 있는 패널(pad: 상·우·하·좌 여백)에 가리지 않게 좌우는 안쪽으로 밀고, 위가 모자라면 점 아래로 둠.
 *  예전에는 늘 점 위 가운데라 가장자리에서 말풍선이 지도 밖으로 나가 글자가 잘렸음 */
export function placeTip(x: number, y: number, tip: Size, map: Size, pad: [number, number, number, number]): { left: number; top: number } {
  const [pt, pr, pb, pl] = pad;
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));   // 넓이가 모자라면 lo(앞부분이 보이게)
  const left = clamp(x - tip.w / 2, pl, map.w - pr - tip.w);
  const above = y - TIP_GAP.above - tip.h, below = y + TIP_GAP.below;
  const top = above >= pt ? above : below + tip.h <= map.h - pb ? below : clamp(above, pt, map.h - pb - tip.h);
  return { left, top };
}
