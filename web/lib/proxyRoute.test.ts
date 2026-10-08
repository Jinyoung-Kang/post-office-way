// @vitest-environment node
// 웹 프록시 라우트(pages/api/v1/[...path].ts)를 실제 HTTP 서버 두 개(가짜 API · 프록시)로 시험 — 끊김이 양쪽으로 전해지는지
import http from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

let upstream: http.Server, front: http.Server, frontPort = 0;
const events: string[] = [];

beforeAll(async () => {
  upstream = http.createServer((req, res) => {
    if (req.url?.startsWith("/api/v1/half")) {                      // 머리글과 본문 일부만 보내고 끊김
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
