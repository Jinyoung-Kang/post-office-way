import { useRouter } from "next/router";
import { useCallback, useEffect, useState } from "react";

// 화면 상태를 주소(?key=value)와 맞춰 두어 새로고침·공유·뒤로 가기에도 같은 화면이 나오게 합니다.
// 같은 틱에 여러 값을 바꿔도 마지막 것만 남지 않도록 한 번에 모아 router.replace 합니다.
let pending: Record<string, string | undefined> = {};
let timer: ReturnType<typeof setTimeout> | null = null;

function replaceQuery(router: ReturnType<typeof useRouter>, patch: Record<string, string | undefined>) {
  pending = { ...pending, ...patch };
  if (timer) return;
  timer = setTimeout(() => {
    const q: Record<string, string> = {};
    Object.entries({ ...router.query, ...pending }).forEach(([k, v]) => {
      if (typeof v === "string" && v !== "") q[k] = v;
    });
    pending = {};
    timer = null;
    router.replace({ pathname: router.pathname, query: q }, undefined, { shallow: true, scroll: false });
  }, 0);
}

// 세 번째 값 ready = 주소 값을 상태에 반영한 뒤 — 그 전에 기본값으로 조회하면 주소에 조건이 있는 화면(?sido=47)이
// 기본 조건으로 한 번, 주소 조건으로 또 한 번 요청함. 같은 화면의 useQueryState 들은 같은 커밋에서 함께 ready 가 됨
export function useQueryState<T extends string>(key: string, def: T, allowed?: readonly T[]): [T, (v: T) => void, boolean] {
  const router = useRouter();
  const [value, setValue] = useState<T>(def);
  const [ready, setReady] = useState(false);
  const raw = router.query[key];
  useEffect(() => {
    if (!router.isReady) return;
    const v = typeof raw === "string" ? (raw as T) : def;
    setValue(allowed && !allowed.includes(v) ? def : v);
    setReady(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, raw]);
  const set = useCallback((v: T) => {
    setValue(v);
    replaceQuery(router, { [key]: v === def ? undefined : v });
  }, [router, key, def]);
  return [value, set, ready];
}
