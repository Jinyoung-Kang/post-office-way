import { describe, expect, it } from "vitest";
import {
  UPSTREAM_IDLE_MS, clientAddress, downstreamResponseHeaders, requestBodyRule, retryOnFreshConnection, upstreamErrorRecord,
  upstreamRequestHeaders,
} from "./proxy";

describe("API 프록시 헤더", () => {
  it("클라이언트가 보낸 X-Forwarded-For 는 버리고 실제 접속 주소로 덮어씀", () => {
    const h = upstreamRequestHeaders({ "x-forwarded-for": "9.9.9.9", "X-Real-IP": "8.8.8.8", forwarded: "for=7.7.7.7",
      accept: "application/json", "accept-encoding": "gzip", host: "evil.example", connection: "keep-alive",
      "x-admin-token": "t" }, "::ffff:172.19.0.1");
    expect(h["x-forwarded-for"]).toBe("172.19.0.1");
    expect(h).not.toHaveProperty("X-Real-IP");
    expect(h).not.toHaveProperty("forwarded");
    expect(h).not.toHaveProperty("host");
    expect(h).not.toHaveProperty("connection");
    expect(h["accept-encoding"]).toBe("gzip");                   // 압축 응답은 그대로 받아 넘김
    expect(h["x-admin-token"]).toBe("t");                        // 관리 API 토큰 헤더는 그대로
  });

  it("접속 주소", () => {
    expect(clientAddress("::ffff:10.0.0.2")).toBe("10.0.0.2");
    expect(clientAddress("2001:db8::1")).toBe("2001:db8::1");
    expect(clientAddress(undefined)).toBe("unknown");
  });

  it("응답의 연결 단위 헤더만 뺌", () => {
    const h = downstreamResponseHeaders({ "content-encoding": "gzip", etag: '"x"', connection: "close",
      "transfer-encoding": "chunked", "x-ratelimit-remaining": "29" });
    expect(h).toEqual({ "content-encoding": "gzip", etag: '"x"', "x-ratelimit-remaining": "29" });
  });
});

describe("요청 본문 규칙 (요청 밀반입 막기)", () => {
  it("POST 만 본문을 흘려보내고, 본문 없는 GET·HEAD 는 본문 없이", () => {
    expect(requestBodyRule("POST", { "content-length": "10" })).toEqual({ kind: "pipe" });
    expect(requestBodyRule("GET", {})).toEqual({ kind: "none" });
    expect(requestBodyRule("HEAD", { "content-length": "0" })).toEqual({ kind: "none" });
  });

  it("본문이 붙은 GET·HEAD 는 400", () => {
    expect(requestBodyRule("GET", { "transfer-encoding": "chunked" })).toMatchObject({ status: 400, code: "VALIDATION_ERROR" });
    expect(requestBodyRule("HEAD", { "content-length": "5" })).toMatchObject({ status: 400 });
  });

  it("API 가 쓰지 않는 메서드는 405", () => {
    for (const m of ["PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", undefined]) {
      expect(requestBodyRule(m, {})).toMatchObject({ kind: "reject", status: 405, code: "METHOD_NOT_ALLOWED" });
    }
  });
});

describe("API 연결 오류 (ADR-029)", () => {
  const reset = { code: "ECONNRESET", message: "socket hang up" };

  it("다시 쓴 연결이 끊긴 GET·HEAD 만 새 연결로 다시 보냄", () => {
    expect(retryOnFreshConnection("GET", reset, true)).toBe(true);
    expect(retryOnFreshConnection("head", { code: "EPIPE", message: "write EPIPE" }, true)).toBe(true);
    expect(retryOnFreshConnection("POST", reset, true)).toBe(false);                    // 계산이 두 번 돌 수 있음
    expect(retryOnFreshConnection("GET", reset, false)).toBe(false);                    // 새 연결도 끊김 — API 문제
    expect(retryOnFreshConnection("GET", { code: "ECONNREFUSED", message: "connect ECONNREFUSED" }, true)).toBe(false);
    expect(retryOnFreshConnection("GET", { message: "timeout" }, true)).toBe(false);    // 60초 시간 초과는 504
  });

  it("오류 기록에 쿼리를 남기지 않음", () => {
    expect(upstreamErrorRecord(reset, { method: "GET", url: "/api/v1/search?q=집주소", reused: true, idleMs: 5000, retry: true }))
      .toEqual({ event: "proxy_upstream_error", method: "GET", path: "/api/v1/search", code: "ECONNRESET",
        message: "socket hang up", reused: true, idleMs: 5000, retry: true });
    expect(upstreamErrorRecord({ message: "timeout" }, { url: undefined, reused: false, idleMs: null, retry: false }))
      .toMatchObject({ method: null, path: "", code: null });
  });

  it("노는 연결을 닫는 시간은 uvicorn 기본 timeout-keep-alive(5초)보다 1초 이상 짧음", () => {
    expect(UPSTREAM_IDLE_MS).toBeLessThanOrEqual(4_000);
    expect(UPSTREAM_IDLE_MS).toBeGreaterThan(0);                                        // 0 이면 노는 연결을 닫지 않음
  });
});
