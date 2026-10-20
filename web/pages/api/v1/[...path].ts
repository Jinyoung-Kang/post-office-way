import http from "node:http";
import type { Socket } from "node:net";
import type { NextApiRequest, NextApiResponse } from "next";
import {
  ALLOWED_METHODS, UPSTREAM_IDLE_MS, downstreamResponseHeaders, requestBodyRule, retryOnFreshConnection, upstreamErrorRecord,
  upstreamRequestHeaders,
} from "@/lib/proxy";

// 브라우저 → 같은 출처 /api/v1/* → FastAPI. rewrites 대신 이 프록시를 쓰는 이유는 X-Forwarded-For 를
// 실제 접속 주소로 덮어쓰기 위해서 (lib/proxy.ts, 리뷰 S1). 본문은 읽지 않고 그대로 흘려보내고(압축·ETag·304 유지),
// 연결 실패·시간 초과는 API 와 같은 오류 형식으로 돌려줌.
export const config = { api: { bodyParser: false, responseLimit: false, externalResolver: true } };

const API = new URL(process.env.API_INTERNAL_BASE || "http://localhost:8100");
const TIMEOUT_MS = 60_000;   // 배치 제안처럼 수 초 걸리는 계산 + 여유 (API 쪽 statement_timeout 15초)
// 프록시 전용 연결 풀 — 노는 연결을 uvicorn 보다 먼저 닫음 (lib/proxy.ts UPSTREAM_IDLE_MS, ADR-029)
const agent = new http.Agent({ keepAlive: true, timeout: UPSTREAM_IDLE_MS });
const lastDone = new WeakMap<Socket, number>();   // 연결마다 마지막 응답을 다 받은 때 — 오류 기록의 idleMs

function fail(res: NextApiResponse, status: number, code: string, message: string) {
  if (res.headersSent || res.destroyed) { res.destroy(); return; }
  res.status(status).json({ code, message, traceId: null });
}

export default function proxy(req: NextApiRequest, res: NextApiResponse) {
  // GET·HEAD 본문은 API 로 넘기지 않음(요청 밀반입 방지), API 가 쓰지 않는 메서드는 보내지 않음 — lib/proxy.ts
  const body = requestBodyRule(req.method, req.headers);
  if (body.kind === "reject") {
    if (body.status === 405) res.setHeader("Allow", ALLOWED_METHODS.join(", "));
    fail(res, body.status, body.code, body.message);
    return;
  }
  let up: http.ClientRequest;
  let gone = false;   // 브라우저가 먼저 끊음 — 그 뒤의 API 오류는 우리가 끊어서 난 것이라 기록·재시도하지 않음

  const send = (retry: boolean) => {
    let sock: Socket | undefined, idleMs: number | null = null;
    const u = http.request({
      protocol: API.protocol, hostname: API.hostname, port: API.port, method: req.method, path: req.url,
      headers: upstreamRequestHeaders(req.headers, req.socket.remoteAddress),
      agent: retry ? false : agent,   // 다시 보낼 때는 풀의 다른 연결(같이 닫혔을 수 있음) 대신 새 연결
    }, (r) => {
      res.writeHead(r.statusCode || 502, downstreamResponseHeaders(r.headers));
      // API 가 본문 도중 끊기면 브라우저 응답도 끊음 — pipe 는 끝내지 않아 브라우저가 멈춰 있었음
      r.on("aborted", () => res.destroy());
      r.on("error", () => res.destroy());
      r.on("end", () => { if (sock) lastDone.set(sock, Date.now()); });
      r.pipe(res);
    });
    up = u;
    u.on("socket", (s) => { sock = s; const t = lastDone.get(s); idleMs = t === undefined ? null : Date.now() - t; });
    u.setTimeout(TIMEOUT_MS, () => u.destroy(new Error("timeout")));
    u.on("error", (e: NodeJS.ErrnoException) => {
      if (gone) return;
      const again = !retry && !res.headersSent && retryOnFreshConnection(req.method, e, u.reusedSocket);
      console.warn(JSON.stringify(upstreamErrorRecord(e, { method: req.method, url: req.url, reused: u.reusedSocket, idleMs, retry: again })));
      if (again) { send(true); return; }
      fail(res, e.message === "timeout" ? 504 : 502, "UPSTREAM_UNAVAILABLE",
        e.message === "timeout" ? "API 응답이 너무 늦습니다." : "API 서버에 연결할 수 없습니다.");
    });
    if (body.kind === "pipe") req.pipe(u);
    else u.end();
  };

  // 브라우저가 먼저 끊으면(페이지 이동·요청 취소) API 요청도 끊음 — GET 은 요청 본문이 이미 끝나 req 'aborted' 가 오지 않음
  res.on("close", () => { if (!res.writableFinished) { gone = true; up.destroy(); } });
  send(false);
}
