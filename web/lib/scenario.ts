// What-if 시나리오 결과와 영향 지도(GeoJSON)를 함께 받는 규칙 (React 와 무관 — vitest 로 시험)
//
// 예전 '계산하기'는 결과를 먼저 화면에 반영하고 지도를 나중에 받아, 지도 요청이 실패하면 새 결과 표와 이전 시나리오 지도가
// 섞이고 주소도 갱신되지 않았음. 성공해도 지도가 두 번 다시 그려졌음. 주소에서 여는 시나리오와 방금 계산한 시나리오가
// 같은 경로로: 둘을 함께 기다려 한 번에 반영하고, 지도만 실패하면 결과는 보이되 지도 자리에 따로 오류를 보임.
export type ScenarioView<W, G> = { result: W; geo: G | null; geoError: Error | null };

export async function scenarioView<W, G>(result: Promise<W>, geo: Promise<G>): Promise<ScenarioView<W, G>> {
  const [w, g] = await Promise.all([
    result,
    geo.then((v) => ({ v, e: null }), (e: unknown) => ({ v: null, e: e instanceof Error ? e : new Error(String(e)) })),
  ]);
  return { result: w, geo: g.v, geoError: g.e };
}
