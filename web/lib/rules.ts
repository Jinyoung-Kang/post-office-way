// 화면 규칙 — 어떤 지역을 먼저 보여 줄지, 순위·진료시간을 어떻게 읽어 줄지. React 없이 값만 다룸
export type Ranked = { value: number | null; lat?: number | null; lon?: number | null };

/** 취약한 쪽부터 n곳 (값이 클수록 나쁜 지표면 내림차순) — 값·좌표 없는 지역은 뺌 */
export function worstFirst<T extends Ranked>(items: T[], higherIsWorse: boolean, n: number): T[] {
  return items.filter((p) => p.value !== null && p.lat != null && p.lon != null)
    .sort((a, b) => (higherIsWorse ? (b.value as number) - (a.value as number) : (a.value as number) - (b.value as number)))
    .slice(0, n);
}

/** 순위 문구 — 나쁠수록 큰 지표는 '나쁜 쪽에서', 아니면 '큰 쪽에서' */
export function rankText(m: { rank: number | null; rankOf: number | null; higherIsWorse: boolean }, fmt: (n: number) => string): string {
  if (m.rank == null || m.rankOf == null) return "—";
  return m.higherIsWorse ? `나쁜 쪽에서 ${fmt(m.rank)}번째` : `큰 쪽에서 ${fmt(m.rank)}번째`;
}

// 국립중앙의료원 진료시간 요일 코드 1~7 = 월~일, 8 = 공휴일
const WEEK = ["", "월", "화", "수", "목", "금", "토", "일", "공휴일"];
const HOUR_DAYS = ["1", "6", "7", "8"];   // 평일 대표(월)·주말·공휴일만 — 말풍선이 길어지지 않게

/** 진료시간 요약 '월 09:00~18:00 · 토 09:00~13:00' (HHMM 문자열) */
export function careHoursText(hours: Record<string, [string, string]> | null | undefined): string {
  return Object.entries(hours || {}).filter(([d]) => HOUR_DAYS.includes(d))
    .map(([d, [a, z]]) => `${WEEK[Number(d)]} ${a.slice(0, 2)}:${a.slice(2)}~${z.slice(0, 2)}:${z.slice(2)}`).join(" · ");
}
