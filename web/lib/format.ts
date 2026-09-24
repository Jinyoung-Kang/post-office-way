// 표기 규칙 — 없는 값은 '—' (NFR-07), 추정·가정이 들어간 값은 ⚠ 표시
export const DASH = "—";

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function dist(m: number | null | undefined): string {
  if (m === null || m === undefined) return DASH;
  return m >= 1000 ? `${num(m / 1000, 2)} km` : `${num(m, 0)} m`;
}

export function withUnit(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return DASH;
  if (unit === "m") return dist(v);
  if (unit === "0/1") return v >= 1 ? "있음" : "없음";
  if (unit === "%") return `${num(v, 1)}%`;
  if (unit === "점") return `${num(v, 1)}점`;
  return `${num(v, 1)}${unit}`;
}

export function dt(s: string | null | undefined): string {
  if (!s) return DASH;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export const short = (id: string | null | undefined) => (id ? id.slice(0, 8) : DASH);

// 순차(단일 색상, 밝음→어두움) 5단계 — 값이 클수록 진함
export const SEQ = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"];
export const NO_DATA = "#e7e6e2";
export const IMPACT = "#eb6834";

/** 분위수 경계 (값이 같은 경계는 합쳐 단계 수가 줄어듦) */
export function quantileBreaks(values: number[], k = SEQ.length): number[] {
  const v = values.filter((x) => x !== null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [];
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

// 시도 이름 약칭 — "경상북도" → "경북", "강원특별자치도" → "강원"
const SIDO_SHORT: Record<string, string> = {
  경상북도: "경북", 경상남도: "경남", 전라남도: "전남", 전라북도: "전북", 충청북도: "충북", 충청남도: "충남",
  전북특별자치도: "전북", 강원특별자치도: "강원", 강원도: "강원", 제주특별자치도: "제주", 경기도: "경기",
  세종특별자치시: "세종",
};
export function shortSido(name: string | null | undefined): string {
  if (!name) return "";
  return SIDO_SHORT[name] ?? name.replace(/(특별시|광역시|특별자치시|통합특별시)$/, "");
}
