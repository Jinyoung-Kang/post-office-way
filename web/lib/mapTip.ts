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
