// 표기 규칙 — 없는 값은 '—' (NFR-07), 추정·가정이 들어간 값은 ⚠ 표시
export const DASH = "—";

// 없는 값·NaN·Infinity(0 으로 나눈 비율 등)는 모두 '—'
const finite = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

export function num(v: number | null | undefined, digits = 0): string {
  if (!finite(v)) return DASH;
  return v.toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function dist(m: number | null | undefined): string {
  if (!finite(m)) return DASH;
  return m >= 1000 ? `${num(m / 1000, 2)} km` : `${num(m, 0)} m`;
}

export function withUnit(v: number | null | undefined, unit: string): string {
  if (!finite(v)) return DASH;
  if (unit === "m") return dist(v);
  if (unit === "0/1") return v >= 1 ? "있음" : "없음";
  if (unit === "%") return `${num(v, 1)}%`;
  if (unit === "점") return `${num(v, 1)}점`;
  if (unit === "명" || unit === "곳" || unit === "개") return `${num(Math.round(v))}${unit}`;   // 사람·시설 수는 정수로 (중앙값이 x.5 여도)
  return `${num(v, 1)}${unit}`;
}

// 시각은 브라우저 시간대가 아니라 서비스 기준(KST)으로 표시 — 서버는 오류 로그 한 줄을 KST 로 만들고
// (atlas/features/error_log.py), 기상청 발표 시각처럼 오프셋 없는 값은 KST 벽시계 시각. 해외 브라우저에서 9시간 어긋났음
const KST_FMT = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});
const KST_PARTS = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  second: "2-digit", hourCycle: "h23",
});

// 서버 시각 문자열 → Date. 오프셋(Z·+09:00)이 있으면 그대로, 없으면 KST 로 봄(날짜만이면 KST 자정)
export function parseKst(s: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T00:00:00+09:00`);
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) return new Date(`${s.replace(" ", "T")}+09:00`);
  return new Date(s);
}

function kstParts(d: Date): Record<"year" | "month" | "day" | "hour" | "minute" | "second", string> {
  const out = { year: "", month: "", day: "", hour: "", minute: "", second: "" };
  for (const p of KST_PARTS.formatToParts(d)) if (p.type in out) out[p.type as keyof typeof out] = p.value;
  return out;
}

export function dt(s: string | null | undefined): string {
  if (!s) return DASH;
  const d = parseKst(s);
  if (Number.isNaN(d.getTime())) return s;
  return KST_FMT.format(d);
}

// 짧게 '월-일 시:분' (KST) — 작업 큐의 다음 실행 시각
export function dtShort(s: string | null | undefined): string {
  if (!s) return DASH;
  const d = parseKst(s);
  if (Number.isNaN(d.getTime())) return s;
  const p = kstParts(d);
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

export const short = (id: string | null | undefined) => (id ? id.slice(0, 8) : DASH);

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

// ⑥ 방문 여건 — 상태 색(좋음·주의·나쁨)은 이 판정에만 씀. 색만으로 구분하지 않도록 항상 글자 라벨과 함께 표시
export const VISIT_FILL: Record<number, string> = { 0: "#b9e2c4", 1: "#ffcf7a", 2: "#f07a80" };
export const VISIT_BADGE: Record<number, string> = { 0: "badge-good", 1: "badge-warn", 2: "badge-error" };
export const VISIT_LABEL: Record<number, string> = { 0: "좋음", 1: "주의", 2: "나쁨" };
export const REASON_LABEL: Record<string, string> = {
  RAIN: "비", SNOW: "눈", HEAT: "더위", COLD: "추위", WIND: "바람", PM10: "미세먼지", PM25: "초미세먼지",
};

// 지표 묶음 — 지표 선택 목록을 주제별 optgroup 으로 (코드가 없으면 '기타')
const METRIC_GROUP: Record<string, string> = {
  NEAREST_FIN_DIST_M: "우체국 거리", POPW_FIN_DIST_M: "우체국 거리", NEAREST_FIN_ROAD_M: "우체국 거리",
  NEAREST_FIN_DRIVE_MIN: "우체국 거리", FAC_CNT_R1KM: "우체국 거리", FAC_CNT_R2KM: "우체국 거리", FAC_CNT_R5KM: "우체국 거리",
  FAR2KM_PPLTN: "멀리 사는 사람", FAR2KM_SHARE: "멀리 사는 사람", AGED65_FAR_PPLTN: "멀리 사는 사람",
  AGED65_PPLTN: "멀리 사는 사람", AGED65_RATIO: "멀리 사는 사람", ACCESS_GAP_SCORE: "멀리 사는 사람",
  NEAREST_BANK_DIST_M: "금융 공백", POST_ONLY_PPLTN: "금융 공백", FIN_DESERT_PPLTN: "금융 공백",
  POST_SOLE_HUB_PPLTN: "생활 거점", LIFE_DESERT_PPLTN: "생활 거점", CARE_DESERT_PPLTN: "생활 거점",
  POPW_PHARMACY_DIST_M: "생활 거점", POPW_CLINIC_DIST_M: "생활 거점", HOLIDAY_CARE_GAP_PPLTN: "생활 거점",
  HAS_365: "운영", LUNCH_CLOSED_RATIO: "운영",
  POPW_FIN_WALK_M: "걸어서", WALK30_NO_FIN_PPLTN: "걸어서", WALK30_NO_FIN_SHARE: "걸어서", WALK30_NO_CASH_PPLTN: "걸어서",
  NET_OUT_12M_PER_1K: "인구 추세", AGED65_NET_IN_12M_PER_1K: "인구 추세",
};
const GROUP_ORDER = ["우체국 거리", "걸어서", "멀리 사는 사람", "금융 공백", "생활 거점", "인구 추세", "운영", "기타"];

// 부호를 붙인 인원 — 순유출·순유입 (+1,234명 · −56명). 0 은 부호 없이
export function signed(v: number | null | undefined, unit = "명"): string {
  if (!finite(v)) return DASH;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v))}${unit}`;
}

// ① 은행 지점 영향 등급 — 상태 색은 등급에만, 늘 글자 라벨과 함께
export const GRADE_LABEL: Record<string, string> = { HIGH: "높음", MID: "보통", LOW: "낮음" };
export const GRADE_BADGE: Record<string, string> = { HIGH: "badge-error", MID: "badge-warn", LOW: "badge-good" };
export const BANK_REASON_SHORT: Record<string, string> = {
  NO_ALT_2KM: "2km 안 대체 없음", NO_ALT_WALK30: "걸어서 30분 안 대체 없음", SAME_BANK_10KM: "같은 은행 10km 밖", AGED_20: "고령 20%+",
};

// 걷는 시간 — 고령자 0.8m/s (서울시 보행약자 신호시간 기준)
export const WALK_MPS = 0.8;
export function walkMin(m: number | null | undefined): string {
  if (m === null || m === undefined || !Number.isFinite(m)) return "—";
  return `${Math.max(1, Math.round(m / WALK_MPS / 60))}분`;
}

export function groupMetrics<T extends { code: string }>(items: T[]): { label: string; items: T[] }[] {
  const by = new Map<string, T[]>();
  items.forEach((m) => { const g = METRIC_GROUP[m.code] || "기타"; by.set(g, [...(by.get(g) || []), m]); });
  return GROUP_ORDER.filter((g) => by.has(g)).map((g) => ({ label: g, items: by.get(g)! }));
}

// 문장 사이 — 마침표·물음표 뒤 공백. 숫자 속 점(0.8m/s)은 뒤가 공백이 아니라 걸리지 않고,
// 공백·여는 괄호 뒤의 숫자만 있는 조각('1. 광화문우체국' 순번, '2026. 10. 08.' 날짜)은 나누지 않음
export const SENTENCE_GAP = /(?<=(?:[^\s\d]|[^\s(\d]\d+)[.?!])\s+/;
// '…니다. …' → 문장 배열. 화면 머리 설명·<Sents> 가 문장마다 줄을 바꾸는 데 씀
export const sentences = (text: string) => text.split(SENTENCE_GAP).filter(Boolean);

// 'YYYY-MM-DD HH:MM:SS' (KST) — 서버 오류 로그 한 줄 형식·시간대와 같게
export function localStamp(d: Date): string {
  const p = kstParts(d);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

