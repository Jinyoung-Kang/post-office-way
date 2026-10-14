import { describe, expect, it } from "vitest";
import { scenarioView } from "./scenario";

const W = { scenarioId: "B", areas: [] };
const G = { features: [{ id: "x" }] };

describe("What-if 시나리오 결과·지도 함께 받기", () => {
  it("둘 다 받으면 함께 — 표와 지도가 한 번에 같은 시나리오로", async () => {
    expect(await scenarioView(Promise.resolve(W), Promise.resolve(G))).toEqual({ result: W, geo: G, geoError: null });
  });

  it("지도 자료만 실패하면 결과는 보이고 지도 오류를 따로 — 이전 시나리오 지도가 남지 않게 geo 는 null", async () => {
    const v = await scenarioView(Promise.resolve(W), Promise.reject(new Error("지도 실패")));
    expect(v.result).toBe(W);
    expect(v.geo).toBeNull();
    expect(v.geoError?.message).toBe("지도 실패");
  });

  it("결과가 실패하면 전체 실패", async () => {
    await expect(scenarioView(Promise.reject(new Error("결과 실패")), Promise.resolve(G))).rejects.toThrow("결과 실패");
  });

  it("Error 가 아닌 거절 값도 Error 로", async () => {
    const v = await scenarioView(Promise.resolve(W), Promise.reject("끊김"));
    expect(v.geoError).toBeInstanceOf(Error);
    expect(v.geoError?.message).toBe("끊김");
  });
});
