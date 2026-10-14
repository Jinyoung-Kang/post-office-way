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

// 요청 본문을 API 로 어떻게 넘길지. API 는 GET·POST 만 씀(HEAD 는 GET 과 같게).
// GET·HEAD 는 본문을 넘기지 않음 — Node 의 http.request 는 GET 에 chunked 를 붙이지 않아(transfer-encoding 은 위에서 뺌)
// 받은 본문 바이트가 경계 없이 API 연결에 그대로 쓰였고, 그 안에 숨긴 두 번째 요청을 API 가 따로 처리했음(요청 밀반입, 리뷰 S2).
// 본문이 붙은 GET·HEAD 는 정상 화면이 보내지 않으므로 400, 그 밖의 메서드는 API 에 보내지 않고 405.
export const ALLOWED_METHODS = ["GET", "HEAD", "POST"] as const;

export type BodyRule =
  | { kind: "pipe" }                    // 본문을 그대로 흘려보냄(POST — Node 가 chunked 로 다시 감쌈)
  | { kind: "none" }                    // 본문 없이 보냄
  | { kind: "reject"; status: 400 | 405; code: string; message: string };

export function requestBodyRule(method: string | undefined, headers: Headers): BodyRule {
  const m = (method || "").toUpperCase();
  if (m === "POST") return { kind: "pipe" };
  if (m !== "GET" && m !== "HEAD") {
    return { kind: "reject", status: 405, code: "METHOD_NOT_ALLOWED", message: "이 주소는 GET·POST 요청만 받습니다." };
  }
  const cl = headers["content-length"];
  if (headers["transfer-encoding"] !== undefined || (cl !== undefined && Number(cl) !== 0)) {
    return { kind: "reject", status: 400, code: "VALIDATION_ERROR", message: "GET 요청에는 본문을 보낼 수 없습니다." };
  }
  return { kind: "none" };
}
