import { useEffect, useRef, type RefObject } from "react";
import { api } from "@/lib/api";
import { bboxParam, diffKeys } from "@/lib/mapGeom";

// 화면 범위 지도 레이어(시설·은행·약국) — 지도를 옮기거나 확대할 때마다 범위 안 항목을 받아 점으로 그림.
// 이전 요청은 취소하고, 받은 목록과 비교해 화면 밖으로 나간 점만 지우고 새로 들어온 점만 만듦
// (예전에는 조금만 옮겨도 모든 점을 지우고 다시 만들었음 — 서울 중구 286개).
export type LayerSpec<T, R> = {
  enabled: boolean;
  maxLevel: number;                     // 이보다 넓게 보면(카카오 level 이 크면) 지우고 onTooFar
  zIndex: number;
  clickable?: boolean;
  path: (bbox: string) => string;       // API 경로
  items: (res: R) => T[];
  keyOf: (item: T) => string;
  draw: (item: T) => HTMLElement;
  onLoaded?: (res: R, shown: number) => void;
  onTooFar?: () => void;
  onError?: (e: Error) => void;
  onDisabled?: () => void;              // 꺼질 때
  onCleanup?: () => void;               // 조건이 바뀌거나 화면을 떠날 때
};

export function useBboxLayer<T extends { lat: number; lon: number }, R>(
  m: { kakao: RefObject<any>; map: RefObject<any>; ready: boolean }, spec: LayerSpec<T, R>, key: string) {
  const s = useRef(spec);
  s.current = spec;                     // 콜백은 늘 최신 — 바뀔 때마다 다시 받지 않게 의존은 enabled·key 만
  const { ready } = m;
  const { enabled } = spec;
  useEffect(() => {
    const kakao = m.kakao.current, map = m.map.current;
    if (!ready || !kakao || !map) return;
    const shown = new Map<string, any>();
    const clear = () => { shown.forEach((o) => o.setMap(null)); shown.clear(); };
    if (!enabled) { s.current.onDisabled?.(); return; }
    let seq = 0;
    let ctl: AbortController | null = null;
    const load = async () => {
      const my = ++seq;
      ctl?.abort();
      if (map.getLevel() > s.current.maxLevel) { clear(); s.current.onTooFar?.(); return; }
      const b = map.getBounds();
      const sw = b.getSouthWest(), ne = b.getNorthEast();
      ctl = new AbortController();
      try {
        const res = await api<R>(s.current.path(bboxParam(sw.getLng(), sw.getLat(), ne.getLng(), ne.getLat())), { signal: ctl.signal });
        if (my !== seq) return;
        const next = new Map(s.current.items(res).map((it) => [s.current.keyOf(it), it]));
        const { remove, add } = diffKeys(shown.keys(), next.keys());
        for (const k of remove) { shown.get(k).setMap(null); shown.delete(k); }
        for (const k of add) {
          const it = next.get(k)!;
          shown.set(k, new kakao.maps.CustomOverlay({ map, position: new kakao.maps.LatLng(it.lat, it.lon),
            content: s.current.draw(it), zIndex: s.current.zIndex, clickable: !!s.current.clickable }));
        }
        s.current.onLoaded?.(res, shown.size);
      } catch (e) {
        if (my === seq) s.current.onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    };
    load();
    const h = () => load();
    kakao.maps.event.addListener(map, "idle", h);
    return () => { kakao.maps.event.removeListener(map, "idle", h); seq++; ctl?.abort(); clear(); s.current.onCleanup?.(); };
  }, [ready, enabled, key, m.kakao, m.map]);
}
