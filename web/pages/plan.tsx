import dynamic from "next/dynamic";
import type AtlasMapType from "@/components/AtlasMap";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import Layout, { Card, Empty, ErrorBox, Hero, Segmented, Stat } from "@/components/Layout";
import type { Marker } from "@/components/AtlasMap";
import { api, qs, type AreaFC, type AreaProps, type PlanClose, type PlanOpen, type Region } from "@/lib/api";
import { classOf, dist, NO_DATA, num, quantileBreaks, SEQ } from "@/lib/format";

const AtlasMap = dynamic(() => import("@/components/AtlasMap"), { ssr: false }) as typeof AtlasMapType;

type Mode = "close" | "open";

// ⑤ 배치 제안 — What-if 를 뒤집어, 범위 안에서 '닫아도 영향이 가장 작은 조합' / '열면 효과가 가장 큰 곳'
export default function PlanPage() {
  const [regions, setRegions] = useState<Region[]>([]);
  const [mode, setMode] = useState<Mode>("close");
  const [sido, setSido] = useState("");
  const [sgg, setSgg] = useState("");
  const [k, setK] = useState(3);
  const [weight, setWeight] = useState<"aged65" | "pop">("aged65");
  const [res, setRes] = useState<PlanClose | PlanOpen | null>(null);
  const [fc, setFc] = useState<AreaFC | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<{ items: Region[] }>("/meta/regions").then((r) => {
      setRegions(r.items);
      const first = r.items.find((x) => x.emdCount > 0);
      if (first) { setSido(first.admCd); setSgg(first.sigungu[0]?.admCd || ""); }
    }).catch(() => null);
  }, []);
  const scope = sgg || sido;

  // 범위의 읍면동 지도 (현재 최근접 거리) — 결과 위치를 보는 바탕
  useEffect(() => {
    if (!scope) return;
    api<AreaFC>(`/areas/geojson${qs({ level: 3, metric: "NEAREST_FIN_DIST_M", parent: scope })}`).then(setFc).catch(() => setFc(null));
  }, [scope]);

  async function run() {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api<PlanClose | PlanOpen>(`/plan/${mode}`, { method: "POST", body: JSON.stringify({ scope, k, weight }) }));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  const breaks = useMemo(() => quantileBreaks((fc?.features || []).map((f) => f.properties.value).filter((v): v is number => v !== null)), [fc]);
  const touched = useMemo(() => new Set(res ? (res.mode === "close" ? res.affectedAreas : res.improvedAreas).map((a) => a.admCd) : []), [res]);
  const styleOf = useCallback((p: AreaProps) => {
    if (res && touched.size) return touched.has(p.admCd) ? { fill: res.mode === "close" ? "#ff6a00" : "#34c759", opacity: 0.7 }
      : { fill: "#e5e5ea", opacity: 0.5 };
    return p.value === null ? { fill: NO_DATA, opacity: 0.5 } : { fill: SEQ[Math.max(classOf(p.value, breaks), 0)], opacity: 0.75 };
  }, [breaks, res, touched]);
  const tooltipOf = useCallback((p: AreaProps) => `최근접 금융 우체국 <b>${dist(p.value)}</b><br/>인구 ${num(p.totPpltn)}명`, []);
  const markers: Marker[] = useMemo(() => !res ? [] : res.mode === "close"
    ? res.steps.map((s, i) => ({ lat: s.lat, lon: s.lon, label: `${i + 1}. ✕ ${s.name}`, tone: "removed" as const }))
    : res.steps.map((s, i) => ({ lat: s.lat, lon: s.lon, label: `${i + 1}. ＋ ${s.siteNm || s.siteCd}`, tone: "new" as const })), [res]);
  const sgus = regions.find((r) => r.admCd === sido)?.sigungu || [];
  const wLabel = (w: string) => (w === "aged65" ? "65세 이상" : "인구");

  return (
    <Layout title="배치 제안">
      <Hero title="어디를, 어떻게." sub="범위를 고르면 ‘닫아도 영향이 가장 작은 우체국 조합’과 ‘새로 열면 효과가 가장 큰 자리’를 계산합니다. 탐욕법 근사이며 결정 근거가 아닌 검토용입니다." />
      <div className="mx-auto grid max-w-wide gap-5 px-4 pb-20 lg:grid-cols-[360px_1fr]">
        <div className="space-y-5">
          <Card title="조건">
            <div className="space-y-4">
              <Segmented ariaLabel="모드" value={mode} onChange={(v) => { setMode(v); setRes(null); }}
                options={[{ value: "close", label: "폐국 영향 최소" }, { value: "open", label: "신설 효과 최대" }]} />
              <div className="grid grid-cols-2 gap-2">
                <select className="field" value={sido} aria-label="시도" onChange={(e) => { setSido(e.target.value); setSgg(""); setRes(null); }}>
                  {regions.filter((r) => r.emdCount > 0).map((r) => <option key={r.admCd} value={r.admCd}>{r.admNm}</option>)}
                </select>
                <select className="field" value={sgg} aria-label="시군구" onChange={(e) => { setSgg(e.target.value); setRes(null); }}>
                  <option value="">시도 전체</option>
                  {sgus.map((s) => <option key={s.admCd} value={s.admCd}>{s.admNm}</option>)}
                </select>
              </div>
              <div>
                <p className="group-label">{mode === "close" ? "닫을" : "열"} 곳 수 · {k}곳</p>
                <input type="range" min={1} max={7} value={k} onChange={(e) => setK(Number(e.target.value))} className="w-full accent-[#0071e3]" aria-label="개수" />
              </div>
              <div>
                <p className="group-label">누구를 기준으로</p>
                <Segmented ariaLabel="가중치" value={weight} onChange={setWeight}
                  options={[{ value: "aged65", label: "65세 이상" }, { value: "pop", label: "전체 인구" }]} />
              </div>
              <button className="btn w-full" disabled={!scope || busy} onClick={run}>{busy ? "계산 중…" : "제안 받기"}</button>
            </div>
          </Card>
          <Card title="이렇게 계산합니다">
            <ul className="space-y-2 text-[13px] leading-relaxed text-ink-2">
              <li><b className="text-ink">폐국 영향 최소</b> — 범위 안 금융 우체국 중, 닫았을 때 ‘가중 인구 × 늘어나는 거리’가 가장 적게 늘어나는 곳을 하나씩 고릅니다(앞서 고른 곳이 닫힌 상태를 반영). 수요는 집계구(평균 약 500명) 단위로 셉니다.</li>
              <li><b className="text-ink">신설 효과 최대</b> — 범위 안 읍면동 대표점을 후보지로, ‘가중 인구 × 줄어드는 거리’가 가장 큰 곳부터 고릅니다.</li>
              <li>단위 <b className="text-ink">명·km</b> = 사람 수 × 늘거나 준 거리. 직선거리·읍면동 대표점 기준.</li>
            </ul>
          </Card>
          {err && <ErrorBox error={err} />}
        </div>

        <div className="space-y-5">
          {res && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              <Stat label="범위" value={res.scopeName || res.scope} note={`후보 ${num(res.candidateCount)}곳 · 기준 ${wLabel(res.weight)}${res.weightFallback ? " (KOSIS 없음 → 인구로 대체)" : ""}${res.mode === "close" ? ` · 수요 ${res.demandUnit === "oa" ? `집계구 ${num(res.demandPoints)}곳` : `읍면동 ${num(res.demandPoints)}곳`}` : " · 수요 읍면동"}`} />
              {res.mode === "close" ? (
                <>
                  <Stat label={`${res.steps.length}곳 닫을 때 늘어나는 거리`} value={`${num(res.totalAddedKmPpl)} 명·km`} note={`${wLabel(res.weight)} 기준`} />
                  <Stat label="새로 2km 밖이 되는 사람" value={`${num(res.totalNewlyFar)}명`} tone={res.totalNewlyFar ? "bad" : undefined} note={wLabel(res.weight)} />
                </>
              ) : (
                <>
                  <Stat label={`${res.steps.length}곳 열 때 줄어드는 거리`} value={`${num(res.totalGainKmPpl)} 명·km`} note={`${wLabel(res.weight)} 기준`} />
                  <Stat label="새로 2km 안이 되는 사람" value={`${num(res.totalNewlyNear)}명`} note={wLabel(res.weight)} />
                </>
              )}
            </div>
          )}
          <div className="card overflow-hidden">
            <AtlasMap<AreaProps> className="h-[460px]" features={fc?.features || []} styleOf={styleOf} tooltipOf={tooltipOf}
              markers={markers} geomKey={scope} />
          </div>
          {!res && <Empty>조건을 고르고 ‘제안 받기’를 누르세요. 지도는 지금의 최근접 금융 우체국 거리입니다(진할수록 멂).</Empty>}
          {res?.mode === "close" && (
            <>
              <Card title="닫는다면 이 순서로" pad={false}>
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="tbl">
                    <thead><tr><th className="num">순서</th><th>우체국</th><th className="num">늘어나는 거리</th><th className="num">새로 2km 밖</th><th className="num">영향 지역</th><th /></tr></thead>
                    <tbody>{res.steps.map((s, i) => (
                      <tr key={s.histId}>
                        <td className="num text-ink-3">{i + 1}</td>
                        <td><span className="font-medium">{s.name}</span><div className="text-[12px] text-ink-3">{s.addr}</div></td>
                        <td className="num">{num(s.addedKmPpl)} 명·km</td>
                        <td className="num">{num(s.newlyFar)}명</td>
                        <td className="num">{s.areasAffected}곳</td>
                        <td><Link className="link text-[13px]" href={`/whatif?add=${s.histId}`}>What-if ›</Link></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
              <Card title="단독으로 닫으면 영향이 가장 큰 곳 (지켜야 할 우체국)" pad={false}>
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="tbl">
                    <thead><tr><th>우체국</th><th className="num">늘어나는 거리</th><th className="num">새로 2km 밖</th><th className="num">영향 지역</th></tr></thead>
                    <tbody>{res.mostCritical.map((s) => (
                      <tr key={s.histId}><td><span className="font-medium">{s.name}</span><div className="text-[12px] text-ink-3">{s.addr}</div></td>
                        <td className="num">{num(s.addedKmPpl)} 명·km</td><td className="num text-[#d70015]">{num(s.newlyFar)}명</td><td className="num">{s.areasAffected}곳</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
          {res?.mode === "open" && (
            <Card title="연다면 이 순서로" pad={false}>
              <div className="overflow-x-auto px-3 pb-3">
                <table className="tbl">
                  <thead><tr><th className="num">순서</th><th>후보지 (읍면동 대표점)</th><th className="num">줄어드는 거리</th><th className="num">새로 2km 안</th><th className="num">좋아지는 지역</th></tr></thead>
                  <tbody>{res.steps.map((s, i) => (
                    <tr key={s.siteCd}><td className="num text-ink-3">{i + 1}</td><td className="font-medium">{s.siteNm || s.siteCd}</td>
                      <td className="num">{num(s.gainKmPpl)} 명·km</td><td className="num text-[#1d8a3a]">{num(s.newlyNear)}명</td><td className="num">{s.areasImproved}곳</td></tr>
                  ))}</tbody>
                </table>
                {!res.steps.length && <p className="px-3 py-4 text-[14px] text-ink-2">이 범위에서는 새로 열어 거리가 줄어드는 곳이 없습니다.</p>}
              </div>
            </Card>
          )}
          {res && (
            <Card title={res.mode === "close" ? "거리가 늘어나는 지역" : "거리가 줄어드는 지역"} pad={false}>
              <div className="max-h-[360px] overflow-auto px-3 pb-3">
                <table className="tbl">
                  <thead><tr><th>지역</th><th className="num">{wLabel(res.weight)}</th><th className="num">전</th><th className="num">후</th></tr></thead>
                  <tbody>{(res.mode === "close" ? res.affectedAreas : res.improvedAreas).map((a) => (
                    <tr key={a.admCd}><td>{a.admNm || a.admCd}</td><td className="num">{num(a.weight)}</td><td className="num">{dist(a.distBeforeM)}</td>
                      <td className={`num font-medium ${a.distAfterM > a.distBeforeM ? "text-[#d70015]" : "text-[#1d8a3a]"}`}>{dist(a.distAfterM)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="px-6 pb-5 text-[12px] text-ink-3">⚠ {res.caveat}</p>
            </Card>
          )}
        </div>
      </div>
    </Layout>
  );
}
