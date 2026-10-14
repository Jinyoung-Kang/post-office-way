// @vitest-environment node
// 웹 프록시 라우트(pages/api/v1/[...path].ts)를 실제 HTTP 서버 두 개(가짜 API · 프록시)로 시험 — 끊김이 양쪽으로 전해지는지,
// 본문 경계가 없는 요청이 API 로 새어 나가지 않는지(요청 밀반입)
import http from "node:http";
import net from "node:net";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

let upstream: http.Server, front: http.Server, frontPort = 0;
const events: string[] = [];
const seen: string[] = [];        // 가짜 API 가 받은 요청 경로 (method + url)

beforeAll(async () => {
  upstream = http.createServer((req, res) => {
    seen.push(`${req.method} ${req.url}`);
    if (req.url?.startsWith("/api/v1/echo")) {                      // 받은 본문을 그대로 돌려줌
      const chunks: Buffer[] = [];
      req.on("data", (c: Buffer) => chunks.push(c));
      req.on("end", () => res.end(JSON.stringify({ method: req.method, body: Buffer.concat(chunks).toString("utf8") })));
    } else if (req.url?.startsWith("/api/v1/half")) {                      // 머리글과 본문 일부만 보내고 끊김
      res.writeHead(200, { "Content-Type": "application/json", "Content-Length": "100" });
      res.write('{"partial":');
      setTimeout(() => res.socket?.destroy(), 50);
    } else if (req.url?.startsWith("/api/v1/slow")) {               // 2초 뒤 응답 — 그 전에 프록시가 끊으면 기록
      const t = setTimeout(() => res.end("{}"), 2000);
      res.on("close", () => { if (!res.writableFinished) { clearTimeout(t); events.push("upstream-closed-early"); } });
    } else res.end("{}");
  });
  await new Promise<void>((r) => upstream.listen(0, "127.0.0.1", r));
  process.env.API_INTERNAL_BASE = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
  const { default: proxy } = await import("@/pages/api/v1/[...path]");
  front = http.createServer((req, res) => {
    // NextApiResponse 의 도우미만 흉내 (오류 응답 경로)
    const r = res as http.ServerResponse & { status: (s: number) => unknown; json: (b: unknown) => void };
    r.status = (s: number) => { r.statusCode = s; return r; };
    r.json = (b: unknown) => { r.setHeader("Content-Type", "application/json"); r.end(JSON.stringify(b)); };
    proxy(req as never, r as never);
  });
  await new Promise<void>((r) => front.listen(0, "127.0.0.1", r));
  frontPort = (front.address() as AddressInfo).port;
});
afterAll(() => { upstream.close(); front.close(); });

describe("웹 프록시 끊김 전달", () => {
  it("API 가 본문 도중 끊기면 브라우저 응답도 끝냄 — 멈춰 있지 않게", async () => {
    const outcome = await new Promise<string>((resolve) => {
      const req = http.get({ port: frontPort, path: "/api/v1/half" }, (res) => {
        res.on("data", () => {});
        res.on("end", () => resolve("end"));
        res.on("aborted", () => resolve("aborted"));
        res.on("error", () => resolve("error"));
        res.on("close", () => resolve("close"));
      });
      req.on("error", () => resolve("req-error"));
      setTimeout(() => resolve("hang"), 1500);
    });
    expect(outcome).not.toBe("hang");
  });

  it("브라우저가 먼저 끊으면 API 요청도 끊음", async () => {
    const req = http.get({ port: frontPort, path: "/api/v1/slow" });
    req.on("error", () => {});
    await new Promise((r) => setTimeout(r, 200));
    req.destroy();
    await new Promise((r) => setTimeout(r, 500));
    expect(events).toContain("upstream-closed-early");
  });
});

// 프록시에 날 요청(raw)을 보내고 응답 전체를 문자열로 받음 — http 클라이언트가 막는 이상한 요청을 그대로 보내려고
function rawRequest(payload: string): Promise<string> {
  return new Promise((resolve) => {
    const sock = net.connect(frontPort, "127.0.0.1");
    let out = "";
    sock.on("data", (d) => { out += d.toString("utf8"); });
    sock.on("close", () => resolve(out));
    sock.on("error", () => resolve(out));
    sock.write(payload);
    setTimeout(() => sock.destroy(), 1500);
  });
}

function request(method: string, path: string, body?: string, headers: Record<string, string> = {}) {
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const req = http.request({ port: frontPort, method, path, headers }, (res) => {
      let b = "";
      res.on("data", (d) => { b += d; });
      res.on("end", () => resolve({ status: res.statusCode || 0, body: b }));
    });
    req.on("error", reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

describe("웹 프록시 요청 본문 경계 (요청 밀반입 막기)", () => {
  it("GET 에 chunked 본문을 붙여 숨긴 요청은 API 에 닿지 않고 400", async () => {
    const hidden = "GET /api/v1/smuggled HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: 203.0.113.77\r\nContent-Length: 0\r\n\r\n";
    const raw = await rawRequest(
      "GET /api/v1/ok HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
      + hidden.length.toString(16) + "\r\n" + hidden + "\r\n0\r\n\r\n");
    await new Promise((r) => setTimeout(r, 300));       // 숨긴 요청이 늦게 닿는 경우까지 기다림
    expect(seen.some((u) => u.includes("/api/v1/smuggled"))).toBe(false);
    expect(raw.split("\r\n")[0]).toBe("HTTP/1.1 400 Bad Request");
    expect(raw).toContain('"code":"VALIDATION_ERROR"');
  });

  it("GET 에 Content-Length 본문이 있으면 400, 본문 없는 GET·HEAD 는 그대로 전달", async () => {
    const before = seen.length;
    const bad = await request("GET", "/api/v1/ok?with-body", "abc", { "Content-Length": "3" });
    expect(bad.status).toBe(400);
    expect(JSON.parse(bad.body)).toMatchObject({ code: "VALIDATION_ERROR", traceId: null });
    expect(seen.slice(before).some((u) => u.includes("with-body"))).toBe(false);

    expect((await request("GET", "/api/v1/ok?plain")).status).toBe(200);
    expect((await request("HEAD", "/api/v1/ok?head")).status).toBe(200);
    expect(seen).toContain("GET /api/v1/ok?plain");
    expect(seen).toContain("HEAD /api/v1/ok?head");
  });

  it("API 가 쓰지 않는 메서드(PUT·DELETE·PATCH·OPTIONS)는 API 에 보내지 않고 405", async () => {
    for (const m of ["PUT", "DELETE", "PATCH", "OPTIONS"]) {
      const before = seen.length;
      const r = await request(m, `/api/v1/ok?m=${m}`, m === "PUT" ? "{}" : undefined);
      expect(r.status).toBe(405);
      expect(JSON.parse(r.body)).toMatchObject({ code: "METHOD_NOT_ALLOWED", traceId: null });
      expect(seen.length).toBe(before);
    }
  });

  it("POST 본문은 그대로 전달 — Content-Length 와 chunked 모두", async () => {
    const body = JSON.stringify({ name: "우체국", n: [1, 2, 3] });
    const fixed = await request("POST", "/api/v1/echo", body,
      { "Content-Type": "application/json", "Content-Length": String(Buffer.byteLength(body)) });
    expect(JSON.parse(fixed.body)).toEqual({ method: "POST", body });

    const chunked = await new Promise<string>((resolve, reject) => {
      const req = http.request({ port: frontPort, method: "POST", path: "/api/v1/echo",
        headers: { "Content-Type": "application/json" } }, (res) => {
        let b = "";
        res.on("data", (d) => { b += d; });
        res.on("end", () => resolve(b));
      });
      req.on("error", reject);
      req.write(body.slice(0, 5));
      setTimeout(() => req.end(body.slice(5)), 30);
    });
    expect(JSON.parse(chunked)).toEqual({ method: "POST", body });
  });
});
