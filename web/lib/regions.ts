// 시도 목록(/meta/regions) 규칙 — React 와 무관한 순수 함수 (hooks/useRegions 가 씀, vitest 로 시험)
//
// 예전에는 여섯 화면이 `useApi(...).data?.items ?? []` 처럼 실패를 빈 목록으로 삼켜, 목록이 꼭 필요한 화면에서
// 읍면동 순위는 끝없는 자리 표시, 배치 제안은 영구 비활성 버튼, 보고서 목록은 빈 화면이 되었음.
import type { Region } from "@/lib/api";

export type Regions = {
  items: Region[];          // 시도 목록 (받기 전·실패면 빈 목록)
  error: Error | null;      // 받지 못한 이유
  loading: boolean;         // 아직 첫 결과(목록·오류)를 받지 않음
  emdAvailable: Region[];   // 읍면동 자료가 있는 시도 — 읍면동 범위를 고르는 화면의 선택지
};

export function regionsOf(s: { data: { items: Region[] } | null; error: Error | null; loading: boolean }): Regions {
  const items = s.data?.items ?? [];
  return { items, error: s.error, loading: !s.data && !s.error, emdAvailable: items.filter((r) => r.emdCount > 0) };
}

// 읍면동 범위(시도)를 골라야 하는 화면이 목록 상태에 따라 보일 것: 고를 수 있음 · 받는 중 · 오류 · 고를 시도 없음
export type EmdNeed = "ok" | "loading" | "error" | "none";

export function emdNeed(r: Regions): EmdNeed {
  if (r.emdAvailable.length) return "ok";
  if (r.error) return "error";
  return r.loading ? "loading" : "none";
}

export function regionsErrorText(e: Error): string {
  return `시도 목록을 불러오지 못했습니다. ${e.message}`;
}

export const NO_EMD_TEXT = "읍면동 자료가 있는 시도가 없습니다 (읍면동 경계를 아직 안 받았다면 make sgis).";
