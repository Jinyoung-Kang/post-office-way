// 지도 화면(/)의 주소 ↔ 상태 규칙 (React·지도 SDK 와 무관한 순수 함수 — vitest 로 시험)
//
// 주소: metric = 지표(기본 지표면 생략), adm = 선택한 지역, in = 읍면동으로 보는 범위(시도 2자리·시군구 5자리)
// 상태: 지표 · 단위(2 시군구 / 3 읍면동) · 읍면동으로 볼 때의 상위 지역 · 선택 지역 · 확대할 지역
import { qs } from "@/lib/api";

export const DEFAULT_METRIC = "ACCESS_GAP_SCORE";

export type MapQuery = { metric?: string; adm?: string; in?: string };
export type MapState = { metric: string; level: 2 | 3; parent: string; selected: string | null; focus: string | null };
type RawQuery = Record<string, string | string[] | undefined>;

// router.query 에서 이 화면이 쓰는 값만 (문자열이 아닌 값 — ?adm=1&adm=2 — 은 없는 것으로)
export function mapQueryFrom(raw: RawQuery): MapQuery {
  const q: MapQuery = {};
  for (const k of ["metric", "adm", "in"] as const) {
    const v = raw[k];
    if (typeof v === "string") q[k] = v;
  }
  return q;
}

export function sameMapQuery(a: MapQuery, b: MapQuery): boolean {
  return a.metric === b.metric && a.adm === b.adm && a.in === b.in;
}

// 주소에 이미 그 값이 그대로 있는지 — 같으면 router.replace 하지 않음 (배열 값은 다름으로 보아 주소를 정리)
export function queryMatches(raw: RawQuery, q: MapQuery): boolean {
  return (raw.metric ?? undefined) === q.metric && (raw.adm ?? undefined) === q.adm && (raw.in ?? undefined) === q.in;
}

// 주소 → 바꿀 상태. 주소에 있는 값만 반영 (순위·개요 화면에서 ?adm=…&metric=… 으로 이동)
export function mapStateOf(q: MapQuery): Partial<MapState> {
  const s: Partial<MapState> = {};
  if (q.metric) s.metric = q.metric;
  if (q.in && !q.adm) { s.level = 3; s.parent = q.in; s.selected = null; s.focus = null; }
  if (q.adm) {
    if (q.adm.length > 5) { s.level = 3; s.parent = q.adm.slice(0, 5); } else { s.level = 2; s.parent = ""; }
    s.selected = q.adm; s.focus = q.adm;
  }
  return s;
}

// 상태 → 주소 (새로고침·공유·뒤로 가기에도 같은 화면). 값이 없는 키는 넣지 않음
export function mapQueryOf(s: Pick<MapState, "metric" | "level" | "parent" | "selected">): MapQuery {
  const q: MapQuery = {};
  if (s.metric !== DEFAULT_METRIC) q.metric = s.metric;
  if (s.selected) q.adm = s.selected;
  if (s.level === 3 && s.parent && !(s.selected && s.selected.length > 5)) q.in = s.parent;
  return q;
}

// 단계구분도 GeoJSON 경로. 요청하지 않음(null):
// - 주소를 아직 상태에 반영하지 않았을 때(ready=false) — 그 전 상태는 기본값이라 ?metric=…·?in=… 화면이
//   기본 지표 전국 GeoJSON(약 200KB gzip)을 먼저 한 번 더 받았음
// - 읍면동인데 상위 지역이 아직 없을 때
export function geojsonPathOf(s: Pick<MapState, "metric" | "level" | "parent">, ready: boolean): string | null {
  if (!ready || (s.level === 3 && !s.parent)) return null;
  return `/areas/geojson${qs({ level: s.level, metric: s.metric, parent: s.parent || undefined })}`;
}

// 지역 카드가 볼 계산 실행 — 지도 자료가 오기 전에는 기다림(null). 기다리지 않으면 계산 실행 없이 한 번,
// 지도 자료가 온 뒤 calcRunId 를 붙여 또 한 번 받아 카드가 깜박였음. 지도 자료를 못 받았으면 최신(undefined)
export function cardRunOf(fc: { meta: { calcRunId: string } } | null, failed: boolean): string | null | undefined {
  if (fc) return fc.meta.calcRunId;
  return failed ? undefined : null;
}

// 지역 카드 경로 — calcRunId 가 null 이면 요청하지 않음
export function regionPathOf(admCd: string, calcRunId: string | null | undefined): string | null {
  if (calcRunId === null) return null;
  return `/areas/${encodeURIComponent(admCd)}${qs({ calcRunId })}`;
}
