// 화면 규칙 — 어떤 지역을 먼저 보여 줄지, 순위·진료시간을 어떻게 읽어 줄지. React 없이 값만 다룸
export type Ranked = { value: number | null; lat?: number | null; lon?: number | null };

/** 취약한 쪽부터 n곳 (값이 클수록 나쁜 지표면 내림차순) — 값·좌표 없는 지역은 뺌 */
export function worstFirst<T extends Ranked>(items: T[], higherIsWorse: boolean, n: number): T[] {
  return items.filter((p) => p.value !== null && p.lat != null && p.lon != null)
    .sort((a, b) => (higherIsWorse ? (b.value as number) - (a.value as number) : (a.value as number) - (b.value as number)))
    .slice(0, n);
}

// 인구 추세 지표(ADR-028)는 '접근성 취약·양호'가 아니라 사람이 빠지는·들어오는 쪽 — 값이 큰 쪽·작은 쪽의 이름
const TREND: Record<string, { big: string; small: string; shade: string }> = {
  NET_OUT_12M_PER_1K: { big: "유출 많은", small: "유입 많은",
    shade: "진할수록 다른 시군구로 나간 사람이 많은 쪽입니다(인구 천 명당, 최근 12개월)." },
  AGED65_NET_IN_12M_PER_1K: { big: "65세 이상 유입 많은", small: "65세 이상 유출 많은",
    shade: "진할수록 65세 이상이 많이 들어온 쪽입니다(65세 이상 천 명당, 최근 12개월)." },
};
export const isTrendMetric = (code: string | null | undefined) => !!code && code in TREND;

/** 순위 문구 — 나쁠수록 큰 지표는 '나쁜 쪽에서', 아니면 '큰 쪽에서'. 인구 추세는 '유출 많은 쪽에서' */
export function rankText(m: { rank: number | null; rankOf: number | null; higherIsWorse: boolean; code?: string },
  fmt: (n: number) => string): string {
  if (m.rank == null || m.rankOf == null) return "—";
  const t = m.code ? TREND[m.code] : undefined;
  if (t) return `${t.big} 쪽에서 ${fmt(m.rank)}번째`;      // 순위는 늘 값이 큰 순(10_ranks.sql)
  return m.higherIsWorse ? `나쁜 쪽에서 ${fmt(m.rank)}번째` : `큰 쪽에서 ${fmt(m.rank)}번째`;
}

/** 순위 화면 머리글 — 지금 정렬(큰 값 먼저인지)이 보여 주는 쪽 */
export function sideText(code: string, higherIsWorse: boolean, bigFirst: boolean): string {
  const t = TREND[code];
  if (t) return `${bigFirst ? t.big : t.small} 쪽`;
  return bigFirst === higherIsWorse ? "접근성 취약 쪽" : "접근성 양호 쪽";
}

/** 지도 색 설명 */
export function shadeText(code: string, higherIsWorse: boolean): string {
  return TREND[code]?.shade ?? (higherIsWorse ? "진할수록 접근성이 취약한 쪽입니다." : "진할수록 값이 큽니다(접근성 양호).");
}

/** 지도 위 8곳 표시 이름 — worstFirst 가 고르는 쪽(나쁠수록 큰 지표면 큰 쪽)과 같게 */
export function topText(code: string, higherIsWorse: boolean): string {
  const t = TREND[code];
  if (t) return `${higherIsWorse ? t.big : t.small} 8곳 표시`;
  return higherIsWorse ? "취약한 8곳 표시" : "값이 작은 8곳 표시";
}

/** 고른 단위에 값이 없는 지표인지 — 인구 추세는 시군구만(원천이 시군구 행렬). 정의를 아직 못 받았으면 false */
export const missingAtLevel = (m: { levels?: number[] } | undefined, level: number) =>
  !!m?.levels?.length && !m.levels.includes(level);
export const LEVEL2_ONLY_TEXT = "이 지표는 시군구 단위만 있습니다.";

/** 배치 제안 경고 — 순유출 상위 20% 시군구 (백분위 기준, 숫자 임계값은 두지 않음) */
export const NET_OUT_WARN_PCT = 80;
export const netOutWarn = (pct: number | null | undefined) => typeof pct === "number" && pct >= NET_OUT_WARN_PCT;

// 국립중앙의료원 진료시간 요일 코드 1~7 = 월~일, 8 = 공휴일
const WEEK = ["", "월", "화", "수", "목", "금", "토", "일", "공휴일"];
const HOUR_DAYS = ["1", "6", "7", "8"];   // 평일 대표(월)·주말·공휴일만 — 말풍선이 길어지지 않게

/** 진료시간 요약 '월 09:00~18:00 · 토 09:00~13:00' (HHMM 문자열) */
export function careHoursText(hours: Record<string, [string, string]> | null | undefined): string {
  return Object.entries(hours || {}).filter(([d]) => HOUR_DAYS.includes(d))
    .map(([d, [a, z]]) => `${WEEK[Number(d)]} ${a.slice(0, 2)}:${a.slice(2)}~${z.slice(0, 2)}:${z.slice(2)}`).join(" · ");
}

/** 은행 지점 영향평가 대상 — 대면 지점이면서 은행(새마을금고·저축은행 제외, BANK-IMPACT-1) */
export function isBankEvaluable(p: { kind: string; brand?: string | null }): boolean {
  return p.kind === "BRANCH" && !!p.brand && p.brand !== "새마을금고" && p.brand !== "저축은행";
}
