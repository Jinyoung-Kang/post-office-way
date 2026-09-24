import dynamic from "next/dynamic";
import type AtlasMapType from "@/components/AtlasMap";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useState } from "react";
import Layout, { basisText, ErrorBox, NoDataGuide, Segmented, useDataBasis } from "@/components/Layout";
import RegionCard, { FacilityCard } from "@/components/RegionCard";
import { BANK_LEGEND, FACILITY_LEGEND, type FacilityLayer } from "@/components/AtlasMap";
import { api, qs, type AreaFC, type AreaProps, type Facility, type MetricDef, type Region } from "@/lib/api";
import { classOf, NO_DATA, num, quantileBreaks, SEQ, withUnit } from "@/lib/format";

const AtlasMap = dynamic(() => import("@/components/AtlasMap"), { ssr: false }) as typeof AtlasMapType;

export default function MapPage() {
  const router = useRouter();
  const { calc } = useDataBasis();
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [metric, setMetric] = useState("ACCESS_GAP_SCORE");
  const [level, setLevel] = useState<2 | 3>(2);
  const [parent, setParent] = useState<string>("");
  const [fc, setFc] = useState<AreaFC | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusCd, setFocusCd] = useState<string | null>(null);
  const [facility, setFacility] = useState<Facility | null>(null);
  const [fac, setFac] = useState<FacilityLayer>(null);
  const [banks, setBanks] = useState(false);
  const [ms, setMs] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [narrow, setNarrow] = useState(false);

  // 휴대폰 폭: 패널은 접은 채 시작, 지도 맞춤 여백도 작게(데스크톱 여백 340px 이 화면보다 넓으면 폴리곤이 밖으로 밀림)
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => setNarrow(mq.matches);
    apply();
    if (mq.matches) setPanelOpen(false);
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    api<{ items: MetricDef[] }>("/metrics").then((r) => setMetrics(r.items.filter((m) => m.available))).catch(() => null);
    api<{ items: Region[] }>("/meta/regions").then((r) => setRegions(r.items)).catch(() => null);
  }, []);

  // ?adm=11010&metric=… (순위·개요 화면에서 이동) → 레벨·상위 전환, 선택, 확대
  useEffect(() => {
    const adm = typeof router.query.adm === "string" ? router.query.adm : null;
    const m = typeof router.query.metric === "string" ? router.query.metric : null;
    if (m) setMetric(m);
    if (adm) {
      if (adm.length > 5) { setLevel(3); setParent(adm.slice(0, 5)); } else { setLevel(2); setParent(""); }
      setSelected(adm); setFocusCd(adm); setFacility(null);
    }
  }, [router.query.adm, router.query.metric]);

  useEffect(() => {
    if (level === 3 && !parent) return;
    let alive = true;
    setLoading(true); setError(null);
    const t0 = performance.now();
    api<AreaFC>(`/areas/geojson${qs({ level, metric, parent: parent || undefined })}`)
      .then((r) => { if (alive) { setFc(r); setMs(Math.round(performance.now() - t0)); } })
      .catch((e) => { if (alive) { setFc(null); setError(e.message); } })
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [level, parent, metric]);

  const breaks = useMemo(() => quantileBreaks((fc?.features || []).map((f) => f.properties.value)
    .filter((v): v is number => v !== null)), [fc]);
  const isBinary = fc?.meta.unit === "0/1";
  const styleOf = useCallback((p: AreaProps) => {
    if (p.value === null) return { fill: NO_DATA, opacity: 0.55 };
    if (isBinary) return { fill: p.value >= 1 ? SEQ[3] : SEQ[0], opacity: 0.8 };
    return { fill: SEQ[Math.max(classOf(p.value, breaks), 0)], opacity: 0.8 };
  }, [breaks, isBinary]);
  const tooltipOf = useCallback((p: AreaProps) =>
    `${fc?.meta.metricName ?? ""} <b>${withUnit(p.value, p.unit)}</b>` +
    (p.rank ? ` · ${p.rank}위/${p.rankOf}` : "") + `<br/>인구 ${num(p.totPpltn)}명`, [fc]);

  const sido = parent.slice(0, 2);
  const sigunguOptions = regions.find((r) => r.admCd === sido)?.sigungu || [];
  const noData = !!error && /CALC_RUN_NOT_FOUND|완료된 계산/.test(error);
  const legend = legendRows(breaks, fc?.meta.unit || "", isBinary);
  const detailOpen = !!(selected || facility);
  const mdef = metrics.find((m) => m.code === metric);

  const chooseLevel = (l: 2 | 3) => {
    setLevel(l); setSelected(null); setFocusCd(null);
    if (l === 2) setParent(""); else if (!parent) setParent(regions.find((r) => r.emdCount > 0)?.admCd || "");
  };

  return (
    <Layout full title="지도">
      <AtlasMap<AreaProps> className="absolute inset-0" features={fc?.features || []} styleOf={styleOf}
        tooltipOf={tooltipOf} selected={selected} geomKey={`${level}:${parent}`} focusCd={focusCd}
        onSelect={(cd) => { setSelected(cd); setFacility(null); }}
        facilities={fac} onFacility={(f) => { setFacility(f); setSelected(null); }} banks={banks}
        padding={narrow ? [90, 16, 16, 16] : [24, detailOpen ? 400 : 24, 24, panelOpen ? 340 : 24]} />

      {/* 왼쪽 떠 있는 패널 — 지표·단위·범례·시설 */}
      <aside className="glass absolute left-3 top-3 z-20 w-[calc(100%-24px)] max-w-[312px] overflow-hidden md:left-4 md:top-4">
        <button className="flex w-full items-center justify-between px-5 pb-2 pt-4 text-left" onClick={() => setPanelOpen(!panelOpen)}
          aria-expanded={panelOpen}>
          <span>
            <span className="block text-[12px] font-medium text-ink-3">지표</span>
            <span className="block text-[17px] font-semibold tracking-tight">{mdef?.name || "…"}</span>
          </span>
          <svg width="12" height="12" viewBox="0 0 12 12" className={`transition-transform ${panelOpen ? "rotate-180" : ""}`}>
            <path d="M2 4l4 4 4-4" stroke="#6e6e73" strokeWidth="1.6" fill="none" strokeLinecap="round" />
          </svg>
        </button>
        {panelOpen && (
          <div className="max-h-[calc(100dvh-140px)] space-y-5 overflow-y-auto px-5 pb-5">
            <select className="field" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="지표 선택">
              {metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}
            </select>
            {fc && <p className="-mt-3 text-[12px] leading-snug text-ink-3">
              {fc.meta.higherIsWorse ? "진할수록 접근성이 취약한 쪽입니다." : "진할수록 값이 큽니다(접근성 양호)."}
            </p>}

            <div className="space-y-2">
              <Segmented ariaLabel="분석 단위" value={level} onChange={chooseLevel}
                options={[{ value: 2, label: "시군구 · 전국" }, { value: 3, label: "읍면동" }]} />
              {level === 3 && (
                <div className="grid grid-cols-2 gap-2">
                  <select className="field" value={sido} aria-label="시도"
                    onChange={(e) => { setParent(e.target.value); setSelected(null); setFocusCd(null); }}>
                    {regions.filter((r) => r.emdCount > 0).map((r) => <option key={r.admCd} value={r.admCd}>{r.admNm}</option>)}
                  </select>
                  <select className="field" value={parent.length === 5 ? parent : ""} aria-label="시군구"
                    onChange={(e) => { setParent(e.target.value || sido); setSelected(null); setFocusCd(null); }}>
                    <option value="">시도 전체</option>
                    {sigunguOptions.map((s) => <option key={s.admCd} value={s.admCd}>{s.admNm}</option>)}
                  </select>
                </div>
              )}
            </div>

            <div>
              <p className="mb-2 text-[12px] font-medium text-ink-3">범례{!isBinary && legend.length > 1 ? " · 분위수" : ""}</p>
              <ul className="space-y-1.5 text-[13px]">
                {legend.map((row) => (
                  <li key={row.label} className="flex items-center gap-2.5">
                    <span className="inline-block h-3 w-6 rounded-[4px]" style={{ background: row.color }} />{row.label}
                  </li>
                ))}
                <li className="flex items-center gap-2.5 text-ink-3">
                  <span className="inline-block h-3 w-6 rounded-[4px]" style={{ background: NO_DATA }} />값 없음
                </li>
              </ul>
            </div>

            <div className="space-y-2">
              <Toggle label="우체국 시설 보기" on={!!fac} onChange={(v) => setFac(v ? { finOnly: false, types: [0, 1, 3] } : null)} />
              {fac && (
                <div className="space-y-2 pl-1 text-[13px]">
                  <Toggle small label="우체통·무인창구·우표판매소" on={fac.types.includes(2)}
                    onChange={(v) => setFac({ ...fac, types: v ? [...fac.types, 2, 4, 5] : fac.types.filter((t) => t < 2 || t === 3) })} />
                  <Toggle small label="금융 가능 우체국만" on={fac.finOnly} onChange={(v) => setFac({ ...fac, finOnly: v })} />
                  <ul className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-[12px] text-ink-2">
                    {FACILITY_LEGEND.map((l) => (
                      <li key={l.label} className="flex items-center gap-1.5">
                        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: l.color }} />{l.label}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="space-y-1">
              <Toggle label="은행·금고 지점 보기" on={banks} onChange={setBanks} />
              {banks && <p className="flex items-center gap-1.5 pl-1 text-[12px] text-ink-2">
                <span className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: BANK_LEGEND.color }} />
                대면 창구(ATM 제외) · 확대하면 보입니다 · 카카오 장소</p>}
            </div>
            {ms !== null && <p className="text-[11px] text-ink-3">{fc?.features.length.toLocaleString()}개 지역 · {ms}ms</p>}
          </div>
        )}
      </aside>

      {/* 오른쪽 떠 있는 패널 — 지역·시설 카드 */}
      {detailOpen && (
        <aside className="glass absolute bottom-3 left-3 right-3 z-20 max-h-[55dvh] overflow-y-auto p-5 md:bottom-auto md:left-auto md:right-4 md:top-4 md:max-h-[calc(100dvh-100px)] md:w-[368px]">
          {facility ? <FacilityCard f={facility} onClose={() => setFacility(null)} /> : selected && (
            <RegionCard admCd={selected} calcRunId={fc?.meta.calcRunId} highlight={metric}
              onClose={() => { setSelected(null); setFocusCd(null); }}
              onDrill={level === 2 ? (cd) => { setLevel(3); setParent(cd); setSelected(null); setFocusCd(null); } : undefined} />
          )}
        </aside>
      )}

      {loading && <div className="glass absolute left-1/2 top-4 z-20 -translate-x-1/2 rounded-full px-4 py-1.5 text-[13px]">불러오는 중…</div>}
      {error && <div className="absolute inset-x-4 top-24 z-30 mx-auto max-w-md">{noData ? <NoDataGuide /> : <ErrorBox error={error} />}</div>}

      <div className="glass absolute bottom-4 left-4 z-10 hidden max-w-[60%] truncate rounded-full px-3 py-1 text-[11px] text-ink-2 md:block">
        {basisText(calc)} · 공식 통계 아님
      </div>
    </Layout>
  );
}

function Toggle({ label, on, onChange, small }: { label: string; on: boolean; onChange: (v: boolean) => void; small?: boolean }) {
  return (
    <label className={`flex cursor-pointer items-center justify-between gap-3 ${small ? "text-[13px]" : "text-[14px] font-medium"}`}>
      {label}
      <span className="relative inline-flex">
        <input type="checkbox" className="peer sr-only" checked={on} onChange={(e) => onChange(e.target.checked)} />
        <span className={`h-[22px] w-[38px] rounded-full transition-colors ${on ? "bg-[#34c759]" : "bg-[rgba(120,120,128,.24)]"}`} />
        <span className={`absolute top-[2px] h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-[2px]"}`} />
      </span>
    </label>
  );
}

function legendRows(breaks: number[], unit: string, binary: boolean) {
  if (binary) return [{ label: "없음", color: SEQ[0] }, { label: "있음", color: SEQ[3] }];
  if (!breaks.length) return [{ label: "모든 지역 같은 값", color: SEQ[0] }];
  const edges = [null, ...breaks, null];
  return edges.slice(0, -1).map((lo, i) => {
    const hi = edges[i + 1];
    const cls = classOf(lo === null ? -Infinity : lo, breaks);
    const label = lo === null ? `${withUnit(hi, unit)} 미만` : hi === null ? `${withUnit(lo, unit)} 이상` : `${withUnit(lo, unit)} – ${withUnit(hi, unit)}`;
    return { label, color: SEQ[Math.max(cls, 0)] };
  });
}
