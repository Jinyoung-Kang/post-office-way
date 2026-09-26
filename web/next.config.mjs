// 브라우저는 같은 출처(/api/v1/*)로 부르고, Next 서버가 FastAPI 로 넘깁니다(CORS·포트 노출 최소화).
// rewrites 는 빌드 시점에 고정되므로 도커 빌드 인자 API_INTERNAL_BASE 로 주소를 넣습니다.
const API = process.env.API_INTERNAL_BASE || "http://localhost:8100";
const dev = process.env.NODE_ENV !== "production";

// 콘텐츠 보안 정책 — 스크립트는 자기 출처 + 카카오 지도 SDK(dapi.kakao.com → *.daumcdn.net)만.
// 지도 타일·마커는 daumcdn 이미지. 스타일은 SSR 된 style 속성과 SDK 가 넣는 스타일 때문에 'unsafe-inline' 허용.
// 개발 모드는 React Refresh 가 eval 을 써서 'unsafe-eval' 이 필요.
// 카카오 SDK 는 페이지 프로토콜을 따라 kakao.js·타일을 받으므로 http 로 띄우면 제3자 스크립트가 평문으로 온다(중간자 주입 위험).
// upgrade-insecure-requests 로 외부 자원을 https 로 올리고, 출처도 https 로만 허용한다(자기 출처 localhost 는 올리지 않음).
const csp = [
  "default-src 'self'",
  `script-src 'self' https://dapi.kakao.com https://*.daumcdn.net${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.daumcdn.net https://*.kakao.com https://*.kakaocdn.net",
  "connect-src 'self' https://dapi.kakao.com https://*.daumcdn.net",
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },   // 카카오 SDK 도메인 확인에 origin 이 필요
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

/** @type {import('next').NextConfig} */
export default {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` },
      { source: "/favicon.ico", destination: "/favicon.svg" },
    ];
  },
};
