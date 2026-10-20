// @vitest-environment node
// 웹 프록시 라우트(pages/api/v1/[...path].ts)를 실제 HTTP 서버 두 개(가짜 API · 프록시)로 시험 — 끊김이 양쪽으로 전해지는지,
// 본문 경계가 없는 요청이 API 로 새어 나가지 않는지(요청 밀반입), keep-alive 연결을 API 와 엇갈리지 않게 닫는지
import http from "node:http";
import net from "node:net";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { UPSTREAM_IDLE_MS } from "./proxy";

let upstream: http.Server, front: http.Server, frontPort = 0;
const events: string[] = [];
const seen: string[] = [];        // 가짜 API 가 받은 요청 경로 (method + url)
const served = new WeakSet<net.Socket>();   // 응답을 한 번 이상 보낸 연결 — keep-alive 로 다시 쓴 연결인지
let dropReused = false;           // 켜면 다시 쓴 연결로 온 다음 요청 하나를 응답 없이 끊음 (uvicorn 이 노는 연결을 닫는 순간)
let idle: { sock: net.Socket; doneAt: number } | undefined;
const idleTimers = new WeakMap<net.Socket, NodeJS.Timeout>();

beforeAll(async () => {
  upstream = http.createServer((req, res) => {
    seen.push(`${req.method} ${req.url}`);
    clearTimeout(idleTimers.get(req.socket));
    if (dropReused && served.has(req.socket)) { dropReused = false; req.socket.destroy(); return; }
    res.on("finish", () => {
      served.add(req.socket);
      // uvicorn 처럼 응답 뒤 5초 동안 다음 요청이 없으면 머리글 예고 없이 연결을 닫음
      idleTimers.set(req.socket, setTimeout(() => req.socket.destroy(), 5_000).unref());
    });
    if (req.url?.startsWith("/api/v1/idle")) {                      // 응답한 연결과 그때를 기록 — 누가 먼저 닫는지 봄
      res.on("finish", () => { idle = { sock: req.socket, doneAt: Date.now() }; });
      res.end("{}");
    } else if (req.url?.startsWith("/api/v1/echo")) {                      // 받은 본문을 그대로 돌려줌
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
  // Node 서버의 keep-alive 는 끔 — 켜 두면 'Keep-Alive: timeout=5' 머리글을 보고 Node 클라이언트가 스스로 1초 먼저 닫아
  // 경쟁이 가려짐. uvicorn 은 이 머리글을 보내지 않음(위 핸들러가 uvicorn 의 5초 닫기를 흉내)
  upstream.keepAliveTimeout = 0;
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

  it("브라우저가 먼저 끊으면 API 요청도 끊음 — 그 끊김은 오류로 기록하거나 다시 보내지 않음", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const req = http.get({ port: frontPort, path: "/api/v1/slow" });
    req.on("error", () => {});
    await new Promise((r) => setTimeout(r, 200));
    req.destroy();
    await new Promise((r) => setTimeout(r, 500));
    expect(events).toContain("upstream-closed-early");
    expect(seen.filter((u) => u.includes("/api/v1/slow"))).toHaveLength(1);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
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

describe("API 와의 keep-alive 연결 (ADR-029)", () => {
  it("다시 쓴 연결이 응답 전에 끊기면 GET 은 새 연결로 한 번 더 보내 200 — 원인은 서버 로그에", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect((await request("GET", "/api/v1/ok?warm")).status).toBe(200);    // 풀에 노는 연결 하나를 남김
    dropReused = true;
    const r = await request("GET", "/api/v1/ok?drop=1&q=secret");
    expect(r.status).toBe(200);
    expect(seen.filter((u) => u.includes("drop=1"))).toHaveLength(2);       // 끊긴 것 + 새 연결
    expect(warn).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(warn.mock.calls[0][0]))).toMatchObject({
      event: "proxy_upstream_error", method: "GET", path: "/api/v1/ok", code: "ECONNRESET", reused: true, retry: true,
    });
    expect(String(warn.mock.calls[0][0])).not.toContain("secret");           // 쿼리는 남기지 않음
    warn.mockRestore();
  });

  it("POST 는 다시 보내지 않고 502 — 계산이 두 번 돌 수 있어서", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect((await request("GET", "/api/v1/ok?warm2")).status).toBe(200);
    dropReused = true;
    const r = await request("POST", "/api/v1/echo?drop=2", "{}", { "Content-Type": "application/json", "Content-Length": "2" });
    expect(r.status).toBe(502);
    expect(JSON.parse(r.body)).toMatchObject({ code: "UPSTREAM_UNAVAILABLE", traceId: null });
    expect(seen.filter((u) => u.includes("drop=2"))).toHaveLength(1);
    expect(JSON.parse(String(warn.mock.calls[0][0]))).toMatchObject({ method: "POST", reused: true, retry: false });
    warn.mockRestore();
  });

  it("노는 연결은 API(5초)보다 먼저 프록시가 닫음 — 닫히는 순간 요청을 보내는 경쟁이 생기지 않게", async () => {
    idle = undefined;
    expect((await request("GET", "/api/v1/idle")).status).toBe(200);
    const sock = idle!.sock, doneAt = idle!.doneAt;
    const closed = await new Promise<{ by: string; ms: number }>((resolve) => {
      sock.once("end", () => resolve({ by: "proxy", ms: Date.now() - doneAt }));    // 프록시가 보낸 FIN
      sock.once("close", () => resolve({ by: "api", ms: Date.now() - doneAt }));    // API 쪽 keep-alive 시간이 먼저 끝남
    });
    expect(closed.by).toBe("proxy");
    expect(closed.ms).toBeGreaterThanOrEqual(UPSTREAM_IDLE_MS - 100);
    expect(closed.ms).toBeLessThan(5_000);
  }, 10_000);
});
