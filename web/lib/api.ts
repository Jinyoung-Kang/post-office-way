// FastAPI 호출 — 같은 출처 /api/v1 (next.config rewrites 가 api 컨테이너로 전달)

export type Meta = { calcRunId: string; statYear: number; facilityAsOf: string; [k: string]: unknown };

export type AreaProps = {
  admCd: string; admNm: string; level: number; parentCd?: string; value: number | null; unit: string;
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
  status?: { state: "open" | "before" | "after" | "closed" | "unknown"; label: string; reason: string | null } | null;
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

export type Bank = { placeId: string; name: string; category: string | null; kind: "BRANCH" | "ATM"; addr: string | null;
  lat: number; lon: number };

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
  weightedAvgDistM: number | null; farPpltn: number; farShare: number | null;
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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
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
