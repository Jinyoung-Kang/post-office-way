import { useCallback, useEffect, useState } from "react";
import { api, cachedApi } from "@/lib/api";

// 조회 Hook — 경로가 바뀌면 이전 요청을 취소하고, 늦게 온 응답은 버림(빠르게 조건을 바꿔도 이전 결과가 덮어쓰지 않게).
// path 가 null 이면 요청하지 않음(주소 값이 아직 준비되지 않았을 때 등). 다시 받는 동안에는 이전 data 를 유지하고 이전 오류는 지움.
// 실패하면 data 를 비우고 error 에 원래 오류 객체(ApiError 면 code·status 포함)를 둠.
export type ApiState<T> = { data: T | null; error: Error | null; loading: boolean; reload: () => void };

type Opts = {
  cacheMs?: number;     // 주면 cachedApi(페이지를 옮겨도 다시 받지 않음, 같은 요청 합침) — 이때는 취소하지 않고 결과만 버림
  keep?: boolean;       // 다시 받는 동안 이전 data 유지 (기본 true). 대상이 바뀌는 상세 화면은 false — 다른 지역 값이 잠깐 보이지 않게
};
export type Outcome<T> = { data: T; error: null } | { data: null; error: Error };

// React 와 무관한 요청 한 번 — 취소 함수를 돌려주고, 취소된 뒤 도착한 결과는 done 에 넘기지 않음 (단위 테스트 대상)
export function startRequest<T>(path: string, cacheMs: number | undefined, done: (o: Outcome<T>) => void): () => void {
  const ctl = new AbortController();
  let alive = true;
  (cacheMs !== undefined ? cachedApi<T>(path, cacheMs) : api<T>(path, { signal: ctl.signal }))
    .then((data) => { if (alive) done({ data, error: null }); })
    .catch((e: unknown) => { if (alive) done({ data: null, error: e instanceof Error ? e : new Error(String(e)) }); });
  return () => { alive = false; ctl.abort(); };
}

export function useApi<T>(path: string | null, { cacheMs, keep = true }: Opts = {}): ApiState<T> {
  const [s, setS] = useState<{ data: T | null; error: Error | null; loading: boolean }>(
    { data: null, error: null, loading: path !== null });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (path === null) { setS({ data: null, error: null, loading: false }); return; }
    setS((p) => (keep ? (p.loading && !p.error ? p : { ...p, error: null, loading: true })
      : { data: null, error: null, loading: true }));
    return startRequest<T>(path, cacheMs, (o) => setS({ ...o, loading: false }));
  }, [path, cacheMs, keep, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...s, reload };
}
