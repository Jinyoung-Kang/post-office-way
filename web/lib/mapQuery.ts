// 지도 화면(/)의 주소 ↔ 상태 규칙 (React·지도 SDK 와 무관한 순수 함수 — vitest 로 시험)
//
// 주소: metric = 지표(기본 지표면 생략), adm = 선택한 지역, in = 읍면동으로 보는 범위(시도 2자리·시군구 5자리)
// 상태: 지표 · 단위(2 시군구 / 3 읍면동) · 읍면동으로 볼 때의 상위 지역 · 선택 지역 · 확대할 지역
import { qs } from "@/lib/api";

export const DEFAULT_METRIC = "ACCESS_GAP_SCORE";

export type MapQuery = { metric?: string; adm?: string; in?: string };
export type MapState = { metric: string; level: 2 | 3; parent: string; selected: string | null; focus: string | null };
export const MAP_DEFAULTS: MapState = { metric: DEFAULT_METRIC, level: 2, parent: "", selected: null, focus: null };
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

// 읍면동을 고른 채 볼 범위: in 이 그 읍면동을 품는 시도(2자리)·시군구(5자리)면 in, 아니면 그 읍면동의 시군구
function emdParent(adm: string, within: string | undefined): string {
  return within && (within.length === 2 || within.length === 5) && adm.startsWith(within) ? within : adm.slice(0, 5);
}

// 주소 → 화면 상태 전부 (순위·개요 화면에서 ?adm=…&metric=… 으로 이동, 뒤로 가기, 머리글의 '/' 링크).
// 주소에 없는 값은 기본값 — 있는 값만 반영하면 파라미터 없는 '/' 로 와도 이전 지표·선택이 남았음
export function mapStateOf(q: MapQuery): MapState {
  const metric = q.metric || DEFAULT_METRIC;
  if (q.adm) {
    return q.adm.length > 5
      ? { metric, level: 3, parent: emdParent(q.adm, q.in), selected: q.adm, focus: q.adm }
      : { metric, level: 2, parent: "", selected: q.adm, focus: q.adm };
  }
  if (q.in) return { metric, level: 3, parent: q.in, selected: null, focus: null };
  return { ...MAP_DEFAULTS, metric };
}

// 상태 → 주소 (새로고침·공유·뒤로 가기에도 같은 화면). 값이 없는 키는 넣지 않음.
// 읍면동을 골랐을 때 in 은 그 읍면동의 시군구와 다를 때만(시도 전체를 보던 중) — 같으면 adm 으로 알 수 있음
export function mapQueryOf(s: Pick<MapState, "metric" | "level" | "parent" | "selected">): MapQuery {
  const q: MapQuery = {};
  if (s.metric !== DEFAULT_METRIC) q.metric = s.metric;
  if (s.selected) q.adm = s.selected;
  const derivable = !!s.selected && s.selected.length > 5 && s.parent === s.selected.slice(0, 5);
  if (s.level === 3 && s.parent && !derivable) q.in = s.parent;
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
