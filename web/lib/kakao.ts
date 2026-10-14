// 카카오 지도 SDK 로더 — 키는 런타임에 /api/config 에서 받아옵니다(재빌드 없이 .env 변경 반영).
declare global {
  interface Window { kakao: any }
}

let loading: Promise<any> | null = null;

const SDK_TIMEOUT_MS = 20_000;     // 아무 신호 없이 본체가 오지 않을 때의 마지막 수단
const BODY_BLOCKED = "카카오 지도 본체를 불러오지 못했습니다. 광고 차단 프로그램·보안 정책(CSP)·네트워크를 확인한 뒤 다시 시도하세요.";
const BODY_TIMEOUT = "카카오 지도를 불러오는 데 너무 오래 걸립니다. 네트워크를 확인한 뒤 다시 시도하세요.";

// 카카오 지도 SDK 가 스크립트를 받는 호스트 — 로더(dapi.kakao.com)와 본체(t1.kakaocdn.net, 예전 t1.daumcdn.net)
export function isKakaoScriptUrl(url: string | undefined): boolean {
  if (!url) return false;
  let host: string;
  try { host = new URL(url).hostname; } catch { return false; }       // CSP 의 'eval'·'inline' 같은 값
  return host === "kakao.com" || host.endsWith(".kakao.com") || host.endsWith(".kakaocdn.net") || host.endsWith(".daumcdn.net");
}

// maps.load 콜백을 기다림. 본체(kakao.js)가 막히면 콜백이 영영 오지 않아 빈 지도로 멈췄음(10-08 CDN 이동 사고와 같은 증상) —
// 본체 스크립트의 로드 실패(문서 캡처 단계 'error')와 CSP 차단을 직접 감지해 거부하고, 마지막 수단으로 시간 제한.
function waitForMaps(): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (err?: Error) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("error", onError, true);
      document.removeEventListener("securitypolicyviolation", onViolation);
      clearTimeout(timer);
      if (err) reject(err); else resolve();
    };
    // script 의 error 는 거품이 일지 않아 캡처 단계에서 받음
    function onError(e: Event) {
      const t = e.target as { tagName?: string; src?: string } | null;
      if (t?.tagName === "SCRIPT" && isKakaoScriptUrl(t.src)) finish(new Error(BODY_BLOCKED));
    }
    // 스크립트 차단만 — kakao.js 의 eval 시도는 일부러 막아 두었고(ADR-013) blockedURI 가 'eval' 이라 여기 걸리지 않음
    function onViolation(e: Event) {
      const v = e as SecurityPolicyViolationEvent;
      if ((v.effectiveDirective || v.violatedDirective || "").startsWith("script-src") && isKakaoScriptUrl(v.blockedURI)) {
        finish(new Error(BODY_BLOCKED));
      }
    }
    document.addEventListener("error", onError, true);
    document.addEventListener("securitypolicyviolation", onViolation);
    const timer = setTimeout(() => finish(new Error(BODY_TIMEOUT)), SDK_TIMEOUT_MS);
    try {
      window.kakao.maps.load(() => finish());
    } catch (e) {
      finish(e instanceof Error ? e : new Error(String(e)));
    }
  });
}

export function loadKakao(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("browser only"));
  if (window.kakao?.maps?.LatLng) return Promise.resolve(window.kakao);
  if (loading) return loading;
  loading = (async () => {
    // 다시 시도할 때 로더(sdk.js)를 이미 받았으면 다시 붙이지 않고 본체만 다시 요청
    if (typeof window.kakao?.maps?.load !== "function") {
      const res = await fetch("/api/config");
      if (!res.ok) throw new Error(`지도 설정을 받지 못했습니다 (HTTP ${res.status}).`);
      const cfg = await res.json();
      if (!cfg.kakaoJsKey) throw new Error("NEXT_PUBLIC_KAKAO_JS_KEY 가 .env 에 없습니다.");
      await new Promise<void>((resolve, reject) => {
        const s = document.createElement("script");
        s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(cfg.kakaoJsKey)}&autoload=false`;
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => {
          s.remove();                    // 다시 시도할 때 실패한 script 태그가 쌓이지 않게
          reject(new Error("카카오 지도 SDK 를 불러오지 못했습니다. 플랫폼 도메인(http://localhost:3100)과 카카오맵 사용 설정(ON)을 확인하세요."));
        };
        document.head.appendChild(s);
      });
      if (typeof window.kakao?.maps?.load !== "function") {
        throw new Error("카카오 지도 SDK 를 받았지만 지도 기능(maps.load)이 없습니다. 잠시 뒤 다시 시도하세요.");
      }
    }
    await waitForMaps();
    return window.kakao;
  })();
  loading.catch(() => { loading = null; });
  return loading;
}

/** GeoJSON (Multi)Polygon → 카카오 Polygon path 목록 (파트마다 [외곽, 구멍…]) */
export function toPaths(kakao: any, geom: { type: string; coordinates: any }): any[][][] {
  const polys: number[][][][] = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  return polys.map((rings) => rings.map((ring) => ring.map(([x, y]) => new kakao.maps.LatLng(y, x))));
}
