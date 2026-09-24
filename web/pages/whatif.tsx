import dynamic from "next/dynamic";
import type AtlasMapType from "@/components/AtlasMap";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useState } from "react";
import Layout, { Card, Empty, ErrorBox, Hero, Segmented, Stat } from "@/components/Layout";
import type { Marker } from "@/components/AtlasMap";
import { api, qs, type Facility, type Feature, type Page, type WhatIf } from "@/lib/api";
import { dist, num } from "@/lib/format";

const AtlasMap = dynamic(() => import("@/components/AtlasMap"), { ssr: false }) as typeof AtlasMapType;

type ImpactProps = { admCd: string; admNm: string; distBeforeM: number | null; distAfterM: number | null;
  increaseM: number | null; affectedPpltn: number | null; affectedAged65: number | null };
type ImpactFC = { features: Feature<ImpactProps>[] };

export default function WhatIfPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Facility[]>([]);
  const [picked, setPicked] = useState<Facility[]>([]);
  const [level, setLevel] = useState<2 | 3>(3);
  const [result, setResult] = useState<WhatIf | null>(null);
  const [geo, setGeo] = useState<ImpactFC | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ms, setMs] = useState<number | null>(null);

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    let alive = true;   // 타이핑 중 늦게 온 이전 검색 결과는 버림
    const t = setTimeout(() => {
      api<Page<Facility>>(`/facilities${qs({ q: q.trim(), finOnly: true, size: 20 })}`)
        .then((r) => { if (alive) setHits(r.items); }).catch(() => { if (alive) setHits([]); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  const load = useCallback(async (id: string) => {
    const [w, g] = await Promise.all([api<WhatIf>(`/whatif/${id}`), api<ImpactFC>(`/whatif/${id}/geojson`)]);
    setResult(w); setGeo(g);
  }, []);

  // ?scenario= 재조회, ?add=histId (지도 시설 카드에서 넘어옴) 미리 선택
  useEffect(() => {
    const id = typeof router.query.scenario === "string" ? router.query.scenario : null;
    if (id && id !== result?.scenarioId) load(id).catch((e) => setErr(e.message));
    const add = typeof router.query.add === "string" ? Number(router.query.add) : null;
    if (add && !picked.some((p) => p.histId === add)) {
      api<Facility>(`/facilities/${add}`).then((f) => setPicked((prev) => prev.some((p) => p.histId === f.histId) ? prev : [...prev, f].slice(0, 5))).catch(() => null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.query.scenario, router.query.add]);

  async function run() {
    setBusy(true); setErr(null);
    const t0 = performance.now();
    try {
      const w = await api<WhatIf>("/whatif", { method: "POST", body: JSON.stringify({ removeHistIds: picked.map((p) => p.histId), level }) });
      setMs(Math.round(performance.now() - t0));
      setResult(w);
      setGeo(await api<ImpactFC>(`/whatif/${w.scenarioId}/geojson`));
      router.replace({ query: { scenario: w.scenarioId } }, undefined, { shallow: true });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  const maxInc = useMemo(() => Math.max(1, ...(geo?.features || []).map((f) => f.properties.increaseM || 0)), [geo]);
  const styleOf = useCallback((p: ImpactProps) => ({
    fill: p.distAfterM === null ? "#d70015" : "#ff6a00",
    opacity: p.distAfterM === null ? 0.75 : 0.28 + 0.55 * Math.min(1, (p.increaseM || 0) / maxInc),
  }), [maxInc]);
  const tooltipOf = useCallback((p: ImpactProps) =>
    `${dist(p.distBeforeM)} → <b>${dist(p.distAfterM)}</b> (+${dist(p.increaseM)})<br/>인구 ${num(p.affectedPpltn)}명` +
    (p.affectedAged65 !== null && p.affectedAged65 !== undefined ? ` · 65세 이상 ${num(p.affectedAged65)}명` : ""), []);
  const markers: Marker[] = useMemo(() => (result?.removed || []).map((r) => ({ lat: r.lat, lon: r.lon, label: `✕ ${r.name}`, tone: "removed" as const })), [result]);
  const hasAged = result?.summary.affectedAged65 !== undefined && result?.summary.affectedAged65 !== null;
  const s = result?.summary;

  return (
    <Layout title="What-if">
      <Hero title="문을 닫는다면." sub="우체국 1~5곳의 폐국을 가정하면, 그 우체국이 가장 가까웠던 지역의 거리가 얼마나 늘어나는지 계산합니다." />
      <div className="mx-auto grid max-w-wide gap-5 px-4 pb-20 lg:grid-cols-[360px_1fr]">
        <div className="space-y-5">
          <Card title="우체국 고르기">
            <input className="field" placeholder="이름이나 주소로 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="우체국 검색" />
            {hits.length > 0 && (
              <ul className="mt-2 max-h-64 overflow-y-auto rounded-[12px] bg-surface p-1 text-[14px]">
                {hits.map((h) => {
                  const on = picked.some((p) => p.histId === h.histId);
                  return (
                    <li key={h.histId}>
                      <button disabled={on || picked.length >= 5} onClick={() => setPicked([...picked, h])}
                        className="w-full rounded-[10px] px-3 py-2 text-left hover:bg-white disabled:opacity-40">
                        <span className="font-medium">{h.name}</span>
                        <span className="block truncate text-[12px] text-ink-3">{h.addr || "—"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="mt-4">
              <p className="group-label">선택 {picked.length}/5</p>
              <div className="group bg-surface">
                {picked.map((p) => (
                  <div key={p.histId} className="row">
                    <span className="truncate font-medium">{p.name}</span>
                    <button className="link shrink-0 text-[13px]" onClick={() => setPicked(picked.filter((x) => x.histId !== p.histId))}>빼기</button>
                  </div>
                ))}
                {!picked.length && <div className="row text-[13px] text-ink-3">검색해서 우체국을 추가하세요. 지도에서 시설을 눌러도 됩니다.</div>}
              </div>
            </div>
            <div className="mt-5 flex items-center justify-between gap-3">
              <Segmented ariaLabel="분석 단위" value={level} onChange={setLevel} options={[{ value: 3, label: "읍면동" }, { value: 2, label: "시군구" }]} />
              <button className="btn" disabled={!picked.length || busy} onClick={run}>{busy ? "계산 중…" : "계산하기"}</button>
            </div>
            {ms !== null && <p className="mt-2 text-[12px] text-ink-3">{ms}ms · 영향 지역만 부분 재계산</p>}
          </Card>
          {err && <ErrorBox error={err} />}
        </div>

        <div className="space-y-5">
          {result && s ? (
            <>
              <div className={`grid grid-cols-2 gap-3 ${hasAged ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
                <Stat label="영향 지역" value={`${num(s.affectedAreas)}곳`} note={s.areasWithoutFacility ? `대체 우체국 없음 ${s.areasWithoutFacility}곳` : undefined} />
                <Stat label="영향 인구" value={`${num(s.affectedPpltn)}명`} note="SGIS 총조사" />
                {hasAged && <Stat label="영향 65세 이상" value={`${num(s.affectedAged65)}명`} tone="bad" note="KOSIS 주민등록" />}
                <Stat label="평균 최근접 거리" value={dist(s.avgDistAfterM)} note={`이전 ${dist(s.avgDistBeforeM)} · 최대 +${dist(s.maxIncreaseM)}`} />
              </div>
              {(s.oaNewlyFarPpltn != null || s.lostFinAccessPpltn != null) && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {s.oaNewlyFarPpltn != null && <Stat label="새로 2km 밖이 되는 인구 · 집계구" value={`${num(s.oaNewlyFarPpltn)}명`}
                    note={`최근접이 바뀌는 인구 ${num(s.oaAffectedPpltn)}명 (집계구 단위, 읍면동 추정보다 정확)`} tone={s.oaNewlyFarPpltn ? "bad" : undefined} />}
                  {s.lostFinAccessPpltn != null && <Stat label="2km 안 금융 창구가 모두 사라지는 인구" value={`${num(s.lostFinAccessPpltn)}명`}
                    note="우체국이 유일한 대면 금융 창구였던 읍면동 (은행·금고 지점도 2km 밖)" tone={s.lostFinAccessPpltn ? "bad" : undefined} />}
                </div>
              )}
              <div className="card overflow-hidden">
                <AtlasMap<ImpactProps> className="h-[440px]" features={geo?.features || []} styleOf={styleOf} tooltipOf={tooltipOf}
                  markers={markers} geomKey={result.scenarioId} padding={[60, 40, 40, 40]} />
              </div>
              <Card title="영향 지역" right={<span className="text-[12px] text-ink-3">거리 증가 큰 순 · scenario {result.scenarioId.slice(0, 8)}</span>} pad={false}>
                {result.areas.length ? (
                  <div className="overflow-x-auto px-3 pb-3">
                    <table className="tbl">
                      <thead><tr><th>지역</th><th className="num">인구</th>{hasAged && <th className="num">65세 이상</th>}<th className="num">전</th><th className="num">후</th><th className="num">증가</th><th>새 최근접</th><th className="num">은행 지점</th></tr></thead>
                      <tbody>
                        {result.areas.map((a) => (
                          <tr key={a.admCd}>
                            <td>{a.parentNm && <span className="text-ink-3">{a.parentNm} </span>}<span className="font-medium">{a.admNm}</span></td>
                            <td className="num">{num(a.affectedPpltn)}</td>
                            {hasAged && <td className="num">{num(a.affectedAged65)}</td>}
                            <td className="num">{dist(a.distBeforeM)}</td>
                            <td className="num font-medium">{dist(a.distAfterM)}</td>
                            <td className="num text-[#d70015]">{a.distAfterM !== null && a.distBeforeM !== null ? `+${dist(a.distAfterM - a.distBeforeM)}` : "—"}</td>
                            <td>{a.newNearestName || "—"}</td>
                            <td className={`num ${a.nearestBankM != null && a.nearestBankM > 2000 ? "text-[#d70015]" : ""}`}>{dist(a.nearestBankM)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <div className="px-6 pb-6"><Empty>이 우체국이 가장 가까운(1순위) 지역이 없어 영향이 없습니다.</Empty></div>}
                <p className="px-6 pb-5 text-[12px] text-ink-3">⚠ {result.caveat}</p>
              </Card>
            </>
          ) : (
            <div className="card flex min-h-[420px] flex-col items-center justify-center p-10 text-center">
              <p className="text-[21px] font-semibold tracking-tight">우체국을 고르고 계산해 보세요.</p>
              <p className="mt-2 max-w-md text-[15px] text-ink-2">영향 지역이 지도에 주황색으로 표시되고, 거리가 많이 늘어난 곳일수록 진해집니다.</p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
