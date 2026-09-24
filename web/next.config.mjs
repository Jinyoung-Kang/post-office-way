// 브라우저는 같은 출처(/api/v1/*)로 부르고, Next 서버가 FastAPI 로 넘깁니다(CORS·포트 노출 최소화).
// rewrites 는 빌드 시점에 고정되므로 도커 빌드 인자 API_INTERNAL_BASE 로 주소를 넣습니다.
const API = process.env.API_INTERNAL_BASE || "http://localhost:8100";

/** @type {import('next').NextConfig} */
export default {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` },
      { source: "/favicon.ico", destination: "/favicon.svg" },
    ];
  },
};
