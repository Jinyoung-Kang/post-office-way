import http from "node:http";
import type { NextApiRequest, NextApiResponse } from "next";
import { downstreamResponseHeaders, upstreamRequestHeaders } from "@/lib/proxy";

// 브라우저 → 같은 출처 /api/v1/* → FastAPI. rewrites 대신 이 프록시를 쓰는 이유는 X-Forwarded-For 를
// 실제 접속 주소로 덮어쓰기 위해서 (lib/proxy.ts, 리뷰 S1). 본문은 읽지 않고 그대로 흘려보내고(압축·ETag·304 유지),
// 연결 실패·시간 초과는 API 와 같은 오류 형식으로 돌려줌.
export const config = { api: { bodyParser: false, responseLimit: false, externalResolver: true } };

const API = new URL(process.env.API_INTERNAL_BASE || "http://localhost:8100");
const TIMEOUT_MS = 60_000;   // 배치 제안처럼 수 초 걸리는 계산 + 여유 (API 쪽 statement_timeout 15초)

function fail(res: NextApiResponse, status: number, code: string, message: string) {
  if (res.headersSent || res.destroyed) { res.destroy(); return; }
  res.status(status).json({ code, message, traceId: null });
}

export default function proxy(req: NextApiRequest, res: NextApiResponse) {
  const up = http.request({
    protocol: API.protocol, hostname: API.hostname, port: API.port, method: req.method, path: req.url,
    headers: upstreamRequestHeaders(req.headers, req.socket.remoteAddress),
  }, (r) => {
    res.writeHead(r.statusCode || 502, downstreamResponseHeaders(r.headers));
    // API 가 본문 도중 끊기면 브라우저 응답도 끊음 — pipe 는 끝내지 않아 브라우저가 멈춰 있었음
    r.on("aborted", () => res.destroy());
    r.on("error", () => res.destroy());
    r.pipe(res);
  });
  up.setTimeout(TIMEOUT_MS, () => up.destroy(new Error("timeout")));
  up.on("error", (e) => fail(res, e.message === "timeout" ? 504 : 502, "UPSTREAM_UNAVAILABLE",
    e.message === "timeout" ? "API 응답이 너무 늦습니다." : "API 서버에 연결할 수 없습니다."));
  // 브라우저가 먼저 끊으면(페이지 이동·요청 취소) API 요청도 끊음 — GET 은 요청 본문이 이미 끝나 req 'aborted' 가 오지 않음
  res.on("close", () => { if (!res.writableFinished) up.destroy(); });
  req.pipe(up);
}
