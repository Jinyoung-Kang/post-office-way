import { useMemo } from "react";
import { useApi } from "@/hooks/useApi";
import type { Region } from "@/lib/api";
import { regionsOf, type Regions } from "@/lib/regions";

// 시도 목록 — 실패를 빈 목록으로 삼키지 않고 error 를 함께 돌려줌(규칙은 lib/regions.ts).
// 10분 캐시(cachedApi)라 여러 화면이 불러도 한 번만 받고, 실패는 캐시하지 않아 화면을 다시 열면 다시 시도.
export function useRegions(): Regions {
  const { data, error, loading } = useApi<{ items: Region[] }>("/meta/regions", { cacheMs: 600_000 });
  return useMemo(() => regionsOf({ data, error, loading }), [data, error, loading]);
}
