// /api/v1/* 프록시가 쓰는 헤더 규칙 (React·Next 와 무관한 순수 함수 — vitest 로 시험)
//
// X-Forwarded-For 는 클라이언트가 마음대로 보낼 수 있으므로 받은 값을 버리고 실제 접속 주소 하나로 덮어씀.
// 예전 rewrites 는 받은 XFF 를 그대로 넘겨 위조한 주소마다 속도 제한 버킷이 새로 생겼고(우회),
// XFF 가 없으면 모든 사용자가 web 컨테이너 주소 하나로 묶였음 (리뷰 S1).

type Headers = Record<string, string | string[] | undefined>;

// 연결 단위(hop-by-hop) 헤더와 클라이언트가 위조할 수 있는 전달 헤더는 넘기지 않음
const DROP_REQUEST = new Set([
  "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
  "transfer-encoding", "upgrade", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded",
]);
const DROP_RESPONSE = new Set(["connection", "keep-alive", "transfer-encoding", "trailer", "upgrade"]);

// '::ffff:172.19.0.1' 같은 IPv4 매핑 주소는 IPv4 로
export function clientAddress(remote: string | undefined): string {
  if (!remote) return "unknown";
  return remote.startsWith("::ffff:") ? remote.slice(7) : remote;
}

export function upstreamRequestHeaders(incoming: Headers, remote: string | undefined): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of Object.entries(incoming)) {
    if (v !== undefined && !DROP_REQUEST.has(k.toLowerCase())) out[k] = v;
  }
  out["x-forwarded-for"] = clientAddress(remote);
  return out;
}

export function downstreamResponseHeaders(upstream: Headers): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of Object.entries(upstream)) {
    if (v !== undefined && !DROP_RESPONSE.has(k.toLowerCase())) out[k] = v;
  }
  return out;
}
