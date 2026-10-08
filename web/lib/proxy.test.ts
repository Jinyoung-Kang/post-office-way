import { describe, expect, it } from "vitest";
import { clientAddress, downstreamResponseHeaders, upstreamRequestHeaders } from "./proxy";

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
