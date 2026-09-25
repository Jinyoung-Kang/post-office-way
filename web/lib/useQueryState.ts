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

export function useQueryState<T extends string>(key: string, def: T, allowed?: readonly T[]): [T, (v: T) => void] {
  const router = useRouter();
  const [value, setValue] = useState<T>(def);
  const raw = router.query[key];
  useEffect(() => {
    if (!router.isReady) return;
    const v = typeof raw === "string" ? (raw as T) : def;
    setValue(allowed && !allowed.includes(v) ? def : v);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, raw]);
  const set = useCallback((v: T) => {
    setValue(v);
    replaceQuery(router, { [key]: v === def ? undefined : v });
  }, [router, key, def]);
  return [value, set];
}
