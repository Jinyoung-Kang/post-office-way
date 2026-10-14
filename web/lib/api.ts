// FastAPI 호출 — 같은 출처 /api/v1 (Next 의 프록시 라우트 pages/api/v1/[...path].ts 가 api 컨테이너로 전달)

export type Meta = { calcRunId: string; statYear: number; facilityAsOf: string; [k: string]: unknown };

export type AreaProps = {
  admCd: string; admNm: string; level: number; parentCd?: string; value: number | null; unit: string;
  lat?: number; lon?: number;          // 대표점(라벨 위치)
  rank: number | null; rankOf: number | null; percentile: number | null; totPpltn: number | null;
  agedChildIdx: number | null;
};
export type Geometry = { type: "Polygon" | "MultiPolygon"; coordinates: number[][][] | number[][][][] };
export type Feature<P> = { type: "Feature"; id?: string; properties: P; geometry: Geometry };
export type AreaFC = { meta: Meta & { metric: string; metricName: string; unit: string; higherIsWorse: boolean };
  type: "FeatureCollection"; features: Feature<AreaProps>[] };

export type MetricDef = { code: string; name: string; unit: string; formula: string; limitation: string | null;
  higherIsWorse: boolean; ruleVersion: string; available: boolean };

export type AreaDetail = {
  admCd: string; admNm: string; level: number; parentCd: string | null; parentNm: string | null; statYear: number;
  areaKm2: number | null; repPoint: { lat: number; lon: number }; bbox: [number, number, number, number];
  population: { totPpltn: number | null; ppltnDnsty: number | null; agedChildIdx: number | null; avgAge: number | null;
    loadedAt: string | null };
  residentPop: { refPeriod: string; totPpltn: number | null; aged65Ppltn: number | null; aged65Ratio: number | null;
    matchMethod: string; loadedAt: string; source: string } | null;
  metrics: { code: string; name: string; value: number | null; unit: string; higherIsWorse: boolean;
    rank: number | null; rankOf: number | null; percentile: number | null }[];
  nearest: { rank: number; histId: number; name: string; distM: number; finAvailable: boolean; addr: string | null;
    financeTime: string | null; lat: number; lon: number; roadM: number | null; driveMin: number | null }[];
  nearestBanks: { name: string; addr: string | null; distM: number; lat: number; lon: number }[];
  facilities: { postDiv: number; divLabel: string; count: number; finCount: number }[];
  meta: Meta;
};

export type Facility = {
  histId: number; postId: string; name: string; postDiv: number; divLabel: string; addr: string | null;
  tel: string | null; lat: number; lon: number; postTime: string | null; financeTime: string | null;
  finAvailable: boolean; lunchYn: string | null; lunchTime: string | null; post365Yn: string | null;
  collectedAt: string; modDt?: string | null; coordSource?: string;
  geocheck?: { status: string; distM: number | null; addrLat: number | null; addrLon: number | null; checkedAt: string } | null;
  // lunch = 점심 휴무 시간대('점심시간 · 13:00 다시 열림'). 화면은 open 만 영업 중(초록)으로 표시
  status?: { state: "open" | "lunch" | "before" | "after" | "closed" | "unknown"; label: string; reason: string | null } | null;
  hub?: FacilityHub | null;
};

// ⑦ 생활 거점 — 이 우체국이 닫히면 2km 안 생활 거점을 모두 잃는 인구, 주변 약국·의원·은행
export type FacilityHub = {
  servedPpltn: number | null; soleFinPpltn: number | null; soleHubPpltn: number | null; oaCount: number | null;
  soleHubRank: number | null; soleHubOf: number | null;
  nearby: { kind: "PHARMACY" | "CLINIC" | "BANK"; name: string; divName: string | null; openHoliday: boolean; distM: number }[];
};
export type HubSummary = {
  meta: Meta; available: boolean;
  care: { pharmacy: number; clinic: number; holidayOpen: number; asOf: string | null };
  totals: { soleHubPpltn: number | null; lifeDesertPpltn: number | null; careDesertPpltn: number | null;
    holidayCareGapPpltn: number | null; popwPharmacyM: number | null; popwClinicM: number | null; oaPpltn: number | null };
  facilities: { withSoleHub: number; withSoleFin: number; served: number };
  topAreas: { admCd: string; admNm: string; parentNm: string | null; value: number; totPpltn: number | null }[];
};
export type HubFacility = { histId: number; name: string; addr: string | null; financeTime: string | null; lat: number; lon: number;
  admCd: string | null; admNm: string | null; parentNm: string | null; servedPpltn: number; soleFinPpltn: number;
  soleHubPpltn: number; oaCount: number };
export type CarePlace = { id: string; kind: "PHARMACY" | "CLINIC"; divName: string | null; name: string; addr: string | null;
  openHoliday: boolean; openSunday: boolean; hours: Record<string, [string, string]>; lat: number; lon: number };
export type CalendarDay = { date: string; weekday: string; closed: boolean; holiday: string | null; reason: string | null;
  runDays: number | null };
export type Job = { jobId: number; kind: string; status: "QUEUED" | "RUNNING" | "DONE" | "FAILED" | "CANCELLED";
  source: string; slot: string | null; attempts: number; error: string | null; createdAt: string; startedAt: string | null;
  finishedAt: string | null; result: Record<string, unknown> | null };
export type ScheduleItem = { kind: string; title: string; group: string; enabled: boolean; note: string; times: string[];
  weekdays: number[] | null; nextRunAt: string | null; missingKeys: string[] };

export type Bank = { placeId: string; name: string; category: string | null; brand?: string | null; kind: "BRANCH" | "ATM";
  addr: string | null; lat: number; lon: number };

export type Page<T> = { items: T[]; page: number; size: number; total: number };

export type Region = { admCd: string; admNm: string; sigunguCount: number; emdCount: number;
  sigungu: { admCd: string; admNm: string }[] };

export type WhatIf = {
  scenarioId: string; level: number; createdAt: string;
  removed: { histId: number; name: string; addr: string | null; lat: number; lon: number }[];
  summary: { affectedAreas: number; affectedPpltn: number; affectedAged65?: number | null; avgDistBeforeM: number | null;
    avgDistAfterM: number | null; maxIncreaseM: number | null; areasWithoutFacility: number;
    lostFinAccessPpltn?: number | null; oaAffectedPpltn?: number | null; oaNewlyFarPpltn?: number | null;
    lifeHubLostPpltn?: number | null };
  areas: { admCd: string; admNm: string; parentNm: string | null; affectedPpltn: number | null; affectedAged65?: number | null;
    distBeforeM: number | null; distAfterM: number | null; newNearestHistId: number | null;
    newNearestName: string | null; lat: number; lon: number; nearestBankM?: number | null }[];
  caveat: string; meta: Meta;
};

export type Overview = {
  facilities: { postDiv: number; label: string; count: number; finCount: number }[];
  facilityTotal: number; finTotal: number; level: number; areaCount: number;
  weightedAvgDistM: number | null; farKm: number; farPpltn: number; farShare: number | null;
  distanceBands: { label: string; areas: number; ppltn: number; share: number | null; aged65: number | null }[];
  kosis: { refPeriod: string; aged65: number; totPpltn: number; aged65Ratio: number | null; aged65Far: number;
    aged65FarShare: number | null } | null;
  topGap: { admCd: string; admNm: string; parentNm: string | null; value: number }[];
  topAgedFar: { admCd: string; admNm: string; parentNm: string | null; value: number }[];
  topPostOnly: { admCd: string; admNm: string; parentNm: string | null; value: number }[];
  oa: { count: number; ppltn: number; popwDistM: number; farPpltn: number; farShare: number } | null;
  finGap: { postOnlyPpltn: number | null; desertPpltn: number | null } | null;
  road: { areas: number; popwRoadM: number; popwStraightM: number; popwDriveMin: number } | null;
  life: { soleHubPpltn: number | null; lifeDesertPpltn: number | null; careDesertPpltn: number | null;
    holidayCareGapPpltn: number | null; soleHubFacilities: number | null } | null;
  topSoleHub: { admCd: string; admNm: string; parentNm: string | null; value: number }[];
  walk: { noFinPpltn: number | null; noCashPpltn: number | null; noFinShare: number | null } | null;
  banks: { branches: number; high: number; lostPpltn: number } | null;
  meta: Meta;
};

export type PlanFacility = { histId: number; name: string; addr: string | null; lat: number; lon: number;
  addedKmPpl: number; newlyFar: number; areasAffected: number; soleHubPpltn?: number | null };
export type PlanArea = { admCd: string; admNm: string | null; weight: number; distBeforeM: number; distAfterM: number };
export type PlanClose = { mode: "close"; scope: string; scopeName: string | null; k: number; level: number; weight: string;
  demandUnit: "oa" | "area"; demandPoints: number;
  weightFallback: boolean; farM: number; candidateCount: number; steps: PlanFacility[]; totalAddedKmPpl: number;
  totalNewlyFar: number; affectedAreas: PlanArea[]; leastImpact: PlanFacility[]; mostCritical: PlanFacility[];
  caveat: string; meta: Meta };
export type PlanOpen = { mode: "open"; scope: string; scopeName: string | null; k: number; level: number; weight: string;
  weightFallback: boolean; farM: number; candidateCount: number;
  steps: { siteCd: string; siteNm: string | null; lat: number; lon: number; gainKmPpl: number; newlyNear: number;
    areasImproved: number }[];
  totalGainKmPpl: number; totalNewlyNear: number; improvedAreas: PlanArea[]; caveat: string; meta: Meta };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

// 자료가 아직 없음(수집·계산 전) — 오류 대신 준비 안내를 보일 경우. 메시지가 아니라 코드로 판정
// (예전에는 메시지에 정규식을 대서, 메시지에 코드가 없는 은행 지점 영향평가 '결과 없음'을 오류로 보였음)
const NO_DATA_CODES = new Set(["CALC_RUN_NOT_FOUND", "BANK_IMPACT_NOT_FOUND"]);

export function isNoData(e: unknown): boolean {
  return e instanceof ApiError && NO_DATA_CODES.has(e.code);
}

// 같은 출처 /api/v1 아래 경로만 — 주소창 값(?scenario= 등)이 섞여도 '..'·'//'·스킴으로 다른 경로를 부르지 못하게
const SAFE_PATH = /^\/(?!.*\.\.)(?!\/)[A-Za-z0-9_\-./?=&%,:+ ]*$/;

// 퍼센트 인코딩한 점('%2e%2e', '.%2E')도 브라우저 URL 정규화에서 '..'·'.' 경로 조각이 되므로, 조각을 풀어 다시 확인
function hasDotSegment(path: string): boolean {
  return path.split(/[?#]/)[0].split("/").some((seg) => {
    try {
      const d = decodeURIComponent(seg);
      return d === "." || d === "..";
    } catch {
      return true;                     // 잘못된 퍼센트 인코딩
    }
  });
}

export function isSafePath(path: string): boolean {
  return SAFE_PATH.test(path) && !hasDotSegment(path);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (!isSafePath(path)) throw new ApiError(400, "BAD_PATH", `허용되지 않은 요청 경로입니다: ${path.slice(0, 80)}`);
  const r = await fetch(`/api/v1${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    let code = "HTTP_ERROR", msg = `HTTP ${r.status}`;
    try { const b = await r.json(); code = b.code || code; msg = b.message || msg; } catch { /* 본문 없음 */ }
    throw new ApiError(r.status, code, msg);
  }
  return r.json() as Promise<T>;
}

// 페이지를 옮겨도 다시 받지 않는 조회용 캐시 — 같은 경로의 동시 요청은 하나로 합치고, 실패는 캐시하지 않음.
// 지표는 계산(calc)이 끝나야 바뀌므로 짧은 TTL 로 충분 (서버도 ETag·304 로 한 번 더 막음)
const CACHE = new Map<string, { at: number; p: Promise<unknown> }>();
const CACHE_MAX = 40;

export function cachedApi<T>(path: string, ttlMs = 60_000): Promise<T> {
  const hit = CACHE.get(path);
  if (hit && Date.now() - hit.at < ttlMs) {
    CACHE.delete(path);                                 // 최근 사용 순서 갱신 (Map 은 삽입 순서)
    CACHE.set(path, hit);
    return hit.p as Promise<T>;
  }
  const p = api<T>(path).catch((e) => { if (CACHE.get(path)?.p === p) CACHE.delete(path); throw e; });
  CACHE.set(path, { at: Date.now(), p });
  while (CACHE.size > CACHE_MAX) CACHE.delete(CACHE.keys().next().value as string);
  return p;
}

export function clearApiCache(prefix = "/"): void {
  for (const k of [...CACHE.keys()]) if (k.startsWith(prefix)) CACHE.delete(k);
}

export function qs(p: Record<string, string | number | boolean | null | undefined>): string {
  const s = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") s.set(k, String(v)); });
  const out = s.toString();
  return out ? `?${out}` : "";
}

// ⑥ 방문 여건 (기상청 단기예보 · 에어코리아 예보, 규칙 VISIT-1)
export type VisitReason = { code: string; level: number; text: string };
export type VisitItem = {
  admCd: string; admNm: string; parentNm: string | null; airRegion: string | null;
  level: 0 | 1 | 2 | null; label: string; reasons: VisitReason[];
  hours: number; tmpMin: number | null; tmpMax: number | null; popMax: number | null; pcpMm: number; snoCm: number;
  wsdMax: number | null; pm10: string | null; pm25: string | null;
  agedFarPpltn: number | null; farPpltn: number | null; nearestFinM: number | null; atRiskAged: number | null;
  has365: boolean | null; holidayCareGapPpltn: number | null; emdWithout365: number | null; emdCount: number | null;
};
export type VisitConditions = {
  meta: { date: string; dates: { date: string; label: string; closed: boolean; closedReason: string | null }[]; window: string;
    weatherBaseAt: string | null; airAnnouncedAt: string | null; ruleVersion: string; calcRunId: string | null; note: string;
    closed: boolean; closedReason: string | null; hasCalendar: boolean };
  items: VisitItem[];
  summary: { areas: number; byLevel: Record<string, number>; byReason: Record<string, number>; atRiskAged: number; atRiskAreas: number;
    holidayCareGapPpltn: number | null; without365Areas: number; emdWithout365: number | null };
};
export type VisitOutlook = { admCd: string; admNm: string; ruleVersion: string;
  days: (VisitItem & { date: string; dayLabel: string; closed: boolean; closedReason: string | null })[] };

// ① 은행 지점 폐쇄 영향평가 (규칙 BANK-IMPACT-1, calc/11_bank_impact.sql + 도보)
export type BankGrade = "HIGH" | "MID" | "LOW";
export type BankImpact = {
  placeId: string; name: string; brand: string | null; addr: string | null; lat: number; lon: number; postAgent: boolean;
  admCd: string | null; admNm: string | null; parentNm: string | null;
  catchOa: number; catchPpltn: number; catchAged: number | null;
  sameBrandM: number | null; otherBankM: number | null; postM: number | null;
  popwNowM: number | null; popwAltM: number | null; lostPpltn: number; lostAged: number | null;
  walkNowM: number | null; walkAltM: number | null; walkLostPpltn: number | null;
  grade: BankGrade; reasons: string[]; rank: number | null; rankOf: number | null;
};
export type BankWalkMeta = { speedMps: number; limitM: number; finishedAt: string; osmLastModified: string | null;
  vertices: number | null } | null;
export type BankListMeta = { fullCrawlAt: string | null; assumption: string };
export type BankImpactList = Page<BankImpact> & {
  summary: { branches: number; high: number; mid: number; low: number; lostPpltn: number; walkLostPpltn: number; catchPpltn: number };
  reasons: Record<string, string>; rule: string; walk: BankWalkMeta; banks: BankListMeta; meta: Meta;
};
export type BankAlt = { kind: "SAME_BANK" | "OTHER_BANK" | "POST"; name: string; sub: string | null; lat: number; lon: number;
  distM: number };
export type BankImpactDetail = {
  item: BankImpact; alternatives: BankAlt[]; altBands: { label: string; oa: number; ppltn: number }[];
  reasons: Record<string, string>; rule: string; walk: BankWalkMeta; banks: BankListMeta; meta: Meta;
};
export type CatchmentProps = { admCd: string; admNm: string; ppltn: number | null; nowM: number | null; altM: number | null;
  aged: number | null };

// ③ 지역 한 장 보고서
export type ReportMetric = { code: string; name: string; unit: string; higherIsWorse: boolean; value: number | null;
  rank: number | null; rankOf: number | null; percentile: number | null; median: number | null };
export type ReportPost = { histId: number; name: string; postDiv: number; financeTime: string | null; has365: boolean;
  lat: number; lon: number; servedPpltn: number | null; soleFinPpltn: number | null; soleHubPpltn: number | null };
export type ReportEmd = { admCd: string; admNm: string; totPpltn: number | null; values: Record<string, number>;
  geometry: Geometry | null };
export type RegionReport = {
  area: { admCd: string; admNm: string; parentCd: string; parentNm: string | null; areaKm2: number; totPpltn: number | null;
    aged65Ppltn: number | null; aged65Ratio: number | null; kosisPeriod: string | null; emdCount: number;
    bbox: [number, number, number, number] };
  metrics: ReportMetric[];
  facilities: { all: number; fin: number; c365: number };
  posts: ReportPost[];
  banks: { branches: number; byGrade: Record<BankGrade, number>; lostPpltn: number;
    top: { placeId: string; name: string; brand: string | null; grade: BankGrade; reasons: string[]; catchPpltn: number;
      lostPpltn: number; walkLostPpltn: number | null }[] };
  emds: ReportEmd[];
  walk: { finishedAt: string } | null;
  visit: VisitOutlook | null;
  meta: Meta & { generatedFor: string };
};
