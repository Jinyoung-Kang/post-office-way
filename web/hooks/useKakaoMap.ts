import { useEffect, useState, type RefObject } from "react";
import { limitView, loadKakao, maskOutside, pinContainer } from "@/lib/kakao";

// 카카오 지도 초기화 — SDK 를 불러와 컨테이너에 지도를 만들고 확대 버튼을 붙임. 컨테이너는 스크롤되지 않게 고정하고,
// 축소 한계는 창 크기에 맞추며 타일 범위 밖은 바다색으로 덮음. 준비되면 ready.
// SDK 를 못 불러오면(키 없음·차단) err 에 이유. 화면을 떠나면 늦게 끝난 초기화는 버림.
// kakao·map 은 부르는 쪽의 useRef — 그쪽 effect 들이 안정된 ref 로 알아보게(의존성 검사)
export function useKakaoMap(el: RefObject<HTMLDivElement | null>, kakao: RefObject<any>, map: RefObject<any>) {
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadKakao().then((k) => {
      if (cancelled || !el.current) return;
      kakao.current = k;
      map.current = new k.maps.Map(el.current, { center: new k.maps.LatLng(36.3, 127.8), level: 12 });
      pinContainer(el.current);
      map.current.addControl(new k.maps.ZoomControl(), k.maps.ControlPosition.RIGHTBOTTOM);
      maskOutside(k, map.current);
      limitView(k, map.current, el.current);
      setReady(true);
    }).catch((e) => setErr(e.message));
    return () => { cancelled = true; };
  }, [el, kakao, map]);
  return { ready, err };
}
