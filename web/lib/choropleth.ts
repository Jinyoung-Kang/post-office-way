// 단계구분도 규칙 — 분위수 경계, 값 → 단계, 범례. React·지도 SDK 없이 값만 다룸 (지도·보고서·배치 제안이 같이 씀)
import { withUnit } from "./format";

// 순차(단일 색상, 밝음→어두움) 5단계 — 값이 클수록 진함
export const SEQ = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"];
export const NO_DATA = "#e7e6e2";

/** 분위수 경계 (값이 같은 경계는 합쳐 단계 수가 줄어듦) */
export function quantileBreaks(values: number[], k = SEQ.length): number[] {
  const v = values.filter((x) => x !== null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [];
  // 최솟값(대개 0)이 30% 넘게 몰린 지표(공백 인구 등)는 최솟값만 첫 단계로 두고 나머지 값으로 분위수 —
  // 그냥 나누면 경계가 겹쳐 '미만/이상' 두 단계만 남음
  const minCount = v.filter((x) => x === v[0]).length;
  if (minCount / v.length > 0.3 && minCount < v.length) {
    const rest = v.slice(minCount);
    const out = [rest[0]];
    for (let i = 1; i < k - 1; i++) {
      const q = rest[Math.min(rest.length - 1, Math.floor((i * rest.length) / (k - 1)))];
      if (q > out[out.length - 1]) out.push(q);
    }
    return out;
  }
  const out: number[] = [];
  for (let i = 1; i < k; i++) {
    const q = v[Math.min(v.length - 1, Math.floor((i * v.length) / k))];
    // 최솟값과 같은 경계는 버림 — 0 이 많은 지표에서 '0명 미만' 같은 빈 구간이 생기지 않게
    if (q > v[0] && (!out.length || q > out[out.length - 1])) out.push(q);
  }
  return out;
}

export function classOf(value: number | null, breaks: number[]): number {
  if (value === null || value === undefined) return -1;
  let i = 0;
  while (i < breaks.length && value >= breaks[i]) i++;
  // 경계가 줄어든 경우에도 가장 진한 색까지 쓰도록 비례 배치
  return breaks.length + 1 >= SEQ.length ? i : Math.round((i / Math.max(breaks.length, 1)) * (SEQ.length - 1));
}

/** 고정 경계(지표 성격에 맞춘 값) → 단계 0..breaks.length, 값 없음 -1 — 지역 사이 비교가 되는 보고서 지도용 */
export function fixedClass(value: number | null | undefined, breaks: readonly number[]): number {
  return value == null ? -1 : breaks.filter((b) => value >= b).length;
}

/** 첫 단계가 최솟값 하나뿐인지(예: 0명) — 그러면 범례 첫 줄을 'x 미만' 대신 그 값으로 */
export function minOnlyValue(values: number[], breaks: number[]): number | null {
  if (!values.length || !breaks.length) return null;
  const min = Math.min(...values);
  return values.every((v) => v >= breaks[0] || v === min) ? min : null;
}

export type LegendRow = { label: string; color: string };

/** 범례 — 0/1 지표는 없음·있음, 경계가 없으면 한 줄, 아니면 '미만 / a – b / 이상' */
export function legendRows(breaks: number[], unit: string, binary: boolean, minOnly: number | null = null): LegendRow[] {
  if (binary) return [{ label: "없음", color: SEQ[0] }, { label: "있음", color: SEQ[3] }];
  if (!breaks.length) return [{ label: "모든 지역 같은 값", color: SEQ[0] }];
  const edges = [null, ...breaks, null];
  return edges.slice(0, -1).map((lo, i) => {
    const hi = edges[i + 1];
    const cls = classOf(lo === null ? -Infinity : lo, breaks);
    const label = lo === null ? (minOnly !== null ? withUnit(minOnly, unit) : `${withUnit(hi, unit)} 미만`) : hi === null ? `${withUnit(lo, unit)} 이상` : `${withUnit(lo, unit)} – ${withUnit(hi, unit)}`;
    return { label, color: SEQ[Math.max(cls, 0)] };
  });
}
