// 시각 표기는 브라우저 시간대가 아니라 서비스 기준(KST) — 해외(UTC) 브라우저를 흉내 내 시험.
// 서버는 오류 로그 한 줄을 KST 로 만들고(atlas/features/error_log.py), 기상청 발표 시각처럼 오프셋 없는 값은 KST 벽시계 시각.
import { afterAll, describe, expect, it } from "vitest";
import { dt, dtShort, localStamp } from "./format";

const prevTZ = process.env.TZ;
process.env.TZ = "UTC";
afterAll(() => { if (prevTZ === undefined) delete process.env.TZ; else process.env.TZ = prevTZ; });

describe("시각 표기 — KST 고정", () => {
  it("브라우저가 UTC 여도 이 기기 시각(Date)은 KST 로 — 서버 오류 로그 한 줄과 같은 시각", () => {
    expect(new Date("2026-10-15T03:00:00Z").getHours()).toBe(3);        // 정말 UTC 로 돌고 있는지
    expect(localStamp(new Date("2026-10-15T03:00:00Z"))).toBe("2026-10-15 12:00:00");
    expect(localStamp(new Date("2026-10-15T15:30:05Z"))).toBe("2026-10-16 00:30:05");   // 날짜도 KST 로 넘어감
  });

  it("오프셋이 있는 값은 KST 로 바꿈", () => {
    expect(dt("2026-10-15T03:00:00+00:00")).toContain("12:00");
    expect(dt("2026-10-15T03:00:00Z")).toContain("12:00");
    expect(dt("2026-10-15T12:00:00+09:00")).toContain("12:00");
  });

  it("오프셋 없는 값(기상청 발표 시각 등)은 KST 벽시계 시각으로", () => {
    expect(dt("2026-10-15T09:00:00")).toContain("09:00");
    expect(dt("2026-10-15T09:00:00")).toContain("2026");
    expect(dt("2026-10-15 09:00:00")).toContain("09:00");
  });

  it("날짜만 있거나 해석할 수 없는 값", () => {
    expect(dt(null)).toBe("—");
    expect(dt("지금")).toBe("지금");
    expect(dt("2026-10-15")).toContain("15");
  });

  it("작업 큐의 '다음 실행'은 같은 KST 포맷으로 짧게 (월-일 시:분)", () => {
    expect(dtShort("2026-10-15T09:00:00+09:00")).toBe("10-15 09:00");
    expect(dtShort("2026-10-15T00:00:00Z")).toBe("10-15 09:00");
    expect(dtShort(null)).toBe("—");
  });
});
