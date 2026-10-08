import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import Layout, { Card, ErrorBox, NoDataGuide, Segmented } from "@/components/Layout";
import MiniMap, { type MiniFeature } from "@/components/MiniMap";
import { StatSkeletons, TableSkeleton } from "@/components/Skeleton";
import { api, cachedApi, type RegionReport, type Region, type ReportMetric } from "@/lib/api";
import { BANK_REASON_SHORT, dt, GRADE_BADGE, GRADE_LABEL, num, VISIT_BADGE, withUnit } from "@/lib/format";
import Sents from "@/components/Sents";

// 읍면동 작은 지도에서 고를 수 있는 지표 — 단계(5칸)는 지표 성격에 맞춘 고정 경계(지역 사이 비교가 되도록)
const EMD_VIEWS = [
  { code: "FAR2KM_SHARE", label: "2km 밖 인구 비율", unit: "%", breaks: [10, 25, 50, 75] },
  { code: "WALK30_NO_FIN_SHARE", label: "걸어서 30분 밖", unit: "%", breaks: [10, 25, 50, 75] },
  { code: "POPW_FIN_DIST_M", label: "평균 거리", unit: "m", breaks: [500, 1000, 2000, 4000] },
  { code: "AGED65_RATIO", label: "고령 비율", unit: "%", breaks: [15, 20, 30, 40] },
] as const;
type EmdCode = (typeof EMD_VIEWS)[number]["code"];
const RAMP = ["#e1ecf8", "#b8d2ee", "#7fabdc", "#4479bf", "#1f4e8c"];   // 한 색조 밝기 순 (값이 클수록 진함)
const NO_DATA = "#e5e5ea";

function rankText(m: ReportMetric): string {
  if (m.rank == null || m.rankOf == null) return "—";
  return m.higherIsWorse ? `나쁜 쪽에서 ${num(m.rank)}번째` : `큰 쪽에서 ${num(m.rank)}번째`;
}

export default function ReportPage() {
  const router = useRouter();
  const admCd = typeof router.query.admCd === "string" ? router.query.admCd : "";
  const [r, setR] = useState<RegionReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<EmdCode>("FAR2KM_SHARE");
  const [regions, setRegions] = useState<Region[]>([]);

  useEffect(() => {
    cachedApi<{ items: Region[] }>("/meta/regions", 600_000).then((x) => setRegions(x.items)).catch(() => null);
  }, []);
  useEffect(() => {
    if (!router.isReady || !admCd) return;
    if (!/^\d{5}$/.test(admCd)) { setErr("지역 보고서는 시군구(5자리 코드) 단위입니다."); return; }
    let alive = true;
    setR(null); setErr(null);
    api<RegionReport>(`/areas/${encodeURIComponent(admCd)}/report`)
      .then((x) => { if (alive) setR(x); }).catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [router.isReady, admCd]);

  const v = EMD_VIEWS.find((x) => x.code === view)!;
  const emdFeatures: MiniFeature[] = useMemo(() => (r?.emds || []).map((e) => {
    const val = e.values[view];
    const cls = val == null ? -1 : v.breaks.filter((b) => val >= b).length;
    return { id: e.admCd, name: e.admNm, geometry: e.geometry, fill: cls < 0 ? NO_DATA : RAMP[cls],
      title: `${e.admNm} — ${v.label} ${val == null ? "자료 없음" : withUnit(val, v.unit)}` };
  }), [r, view, v]);
  const emdRows = useMemo(() => [...(r?.emds || [])].sort((a, b) => (b.values[view] ?? -1) - (a.values[view] ?? -1)), [r, view]);
  const sido = regions.find((x) => x.admCd === admCd.slice(0, 2));
  const noData = !!err && /CALC_RUN_NOT_FOUND|완료된 계산/.test(err);
  const title = r ? `${r.area.parentNm ? r.area.parentNm + " " : ""}${r.area.admNm}` : "지역 보고서";

  return (
    <Layout title={r ? `${r.area.admNm} 보고서` : "지역 보고서"}>
      <div className="report mx-auto max-w-page space-y-5 px-4 pb-20 pt-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow mb-1">지역 보고서 · 우체국 가는 길</p>
            <h1 className="text-[34px] font-semibold leading-tight tracking-tight">{title}</h1>
            {r && <p className="mt-1 text-[13px] text-ink-3">
              {dt(new Date().toISOString())} 출력 · 지표 calcRun {r.meta.calcRunId.slice(0, 8)} · 시설 기준 {dt(r.meta.facilityAsOf)}</p>}
          </div>
          <div className="no-print flex flex-wrap items-center gap-2">
            <select name="sido" className="field w-auto py-1.5 text-[13px]" aria-label="시도" value={admCd.slice(0, 2)}
              onChange={(e) => { const s = regions.find((x) => x.admCd === e.target.value); if (s?.sigungu[0]) router.push(`/report/${s.sigungu[0].admCd}`); }}>
              {regions.map((x) => <option key={x.admCd} value={x.admCd}>{x.admNm}</option>)}
            </select>
            <select name="sgg" className="field w-auto py-1.5 text-[13px]" aria-label="시군구" value={admCd}
              onChange={(e) => router.push(`/report/${e.target.value}`)}>
              {(sido?.sigungu || []).map((x) => <option key={x.admCd} value={x.admCd}>{x.admNm}</option>)}
            </select>
            <button className="btn" onClick={() => window.print()} disabled={!r}>인쇄 · PDF 저장</button>
          </div>
        </div>

        {err && (noData ? <NoDataGuide /> : <ErrorBox error={err} />)}
        {!r && !err && <><StatSkeletons rows={1} /><div className="card p-6"><TableSkeleton rows={8} /></div></>}
        {r && (
          <>
            <section className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="요약">
              <Fact label="인구" value={`${num(r.area.totPpltn)}명`} note={`면적 ${num(r.area.areaKm2)}km² · 읍면동 ${r.area.emdCount}곳`} />
              <Fact label="65세 이상" value={r.area.aged65Ratio != null ? `${num(r.area.aged65Ratio, 1)}%` : "—"}
                note={r.area.aged65Ppltn != null ? `${num(r.area.aged65Ppltn)}명 · KOSIS ${r.area.kosisPeriod}` : "KOSIS 자료 없음"} />
              <Fact label="금융 우체국" value={`${num(r.facilities.fin)}곳`} note={`전체 시설 ${num(r.facilities.all)}곳 · 365코너 ${num(r.facilities.c365)}곳`} />
              <Fact label="은행 지점" value={`${num(r.banks.branches)}곳`}
                note={`닫힐 때 영향 높음 ${r.banks.byGrade.HIGH} · 보통 ${r.banks.byGrade.MID} · 낮음 ${r.banks.byGrade.LOW}`} />
            </section>

            <Card title="핵심 지표 — 전국 시군구와 비교">
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead className="whitespace-nowrap"><tr><th>지표</th><th className="num">이 지역</th><th className="num">전국 시군구 중앙값</th>
                    <th>전국 252곳 중</th></tr></thead>
                  <tbody>{r.metrics.map((m) => {
                    const worse = m.median != null && m.value != null && (m.higherIsWorse ? m.value > m.median : m.value < m.median);
                    return (
                      <tr key={m.code}>
                        <td className="min-w-[180px]">{m.name}</td>
                        <td className={`num font-semibold ${worse ? "text-[#d70015]" : ""}`}>{withUnit(m.value, m.unit)}</td>
                        <td className="num text-ink-2">{withUnit(m.median, m.unit)}</td>
                        <td className="whitespace-nowrap text-[13px]">
                          <span className="tnum inline-block w-34">{rankText(m)}</span>
                          {m.percentile != null && <span className="ml-2 inline-block h-1.5 w-20 rounded-full bg-surface align-middle" aria-hidden="true">
                            <span className="block h-1.5 rounded-full bg-[#4479bf]" style={{ width: `${m.percentile}%` }} /></span>}
                        </td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
              <p className="mt-3 text-[12px] text-ink-3"><Sents>빨간 값은 전국 시군구 중앙값보다 나쁜 쪽. 막대는 값의 백분위(오른쪽일수록 큼).
                {r.walk ? " ‘걸어서’ 지표는 OSM 보행 도로망 · 고령자 0.8m/s." : " 도보 지표는 아직 계산 전입니다."}</Sents></p>
            </Card>

            <Card title="읍면동" right={<div className="no-print min-w-0 max-w-full"><Segmented ariaLabel="읍면동 지표" value={view} onChange={setView}
              options={EMD_VIEWS.map((x) => ({ value: x.code, label: x.label }))} /></div>}>
              <div className="grid grid-cols-1 gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <MiniMap features={emdFeatures} label={`${r.area.admNm} 읍면동별 ${v.label}`} />
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-ink-2" aria-label="범례">
                    <span className="font-medium">{v.label}</span>
                    {RAMP.map((c, i) => <span key={c} className="inline-flex items-center gap-1">
                      <span className="inline-block h-3 w-3 rounded-[3px]" style={{ background: c }} />
                      {i === 0 ? `< ${withUnit(v.breaks[0], v.unit)}` : i === RAMP.length - 1 ? `${withUnit(v.breaks[i - 1], v.unit)} +` : `${num(v.breaks[i - 1])}~${withUnit(v.breaks[i], v.unit)}`}
                    </span>)}
                    <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-[3px]" style={{ background: NO_DATA }} />자료 없음</span>
                  </div>
                </div>
                <div className="max-h-[420px] overflow-auto print:max-h-none" tabIndex={0} role="region" aria-label={`${r.area.admNm} 읍면동 표`}>
                  <table className="tbl">
                    <thead className="whitespace-nowrap"><tr><th>읍면동</th><th className="num">인구</th><th className="num">{v.label}</th></tr></thead>
                    <tbody>{emdRows.map((e) => (
                      <tr key={e.admCd}><td>{e.admNm}</td><td className="num">{num(e.totPpltn)}</td>
                        <td className="num font-medium">{withUnit(e.values[view], v.unit)}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </div>
            </Card>

            <Card title="지켜야 할 우체국" right={<span className="text-[12px] text-ink-3">닫히면 대신할 곳이 없는 주민 많은 순</span>}>
              {r.posts.length ? (
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead className="whitespace-nowrap"><tr><th>우체국</th><th>금융 창구</th><th className="num">담당 인구</th>
                      <th className="num">금융 대체 불가</th><th className="num">마지막 생활 거점</th></tr></thead>
                    <tbody>{r.posts.map((p) => (
                      <tr key={p.histId}>
                        <td className="whitespace-nowrap font-medium">{p.name}{p.has365 && <span className="badge badge-info ml-2">365</span>}</td>
                        <td className="whitespace-nowrap text-[13px] text-ink-2">{p.financeTime || "—"}</td>
                        <td className="num">{num(p.servedPpltn)}</td>
                        <td className="num">{num(p.soleFinPpltn)}</td>
                        <td className={`num font-semibold ${p.soleHubPpltn ? "text-[#d70015]" : "text-ink-3"}`}>{num(p.soleHubPpltn)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <p className="text-[14px] text-ink-2">이 지역에 금융 우체국이 없습니다.</p>}
            </Card>

            <Card title="은행 지점이 문을 닫으면" right={<Link href={`/banks?sido=${admCd.slice(0, 2)}`} className="link no-print text-[13px]">은행 지점 영향평가 ›</Link>}>
              {r.banks.top.length ? (
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead className="whitespace-nowrap"><tr><th>지점</th><th>영향</th><th className="num">이용 주민</th>
                      <th className="num">새로 잃는 주민</th><th className="num">걸어서</th><th>요인</th></tr></thead>
                    <tbody>{r.banks.top.map((b) => (
                      <tr key={b.placeId}>
                        <td className="whitespace-nowrap"><Link href={`/banks?id=${b.placeId}`} className="font-medium text-ink no-underline">{b.name}</Link></td>
                        <td><span className={`badge ${GRADE_BADGE[b.grade]}`}>{GRADE_LABEL[b.grade]}</span></td>
                        <td className="num">{num(b.catchPpltn)}</td>
                        <td className={`num ${b.lostPpltn ? "font-semibold text-[#d70015]" : ""}`}>{num(b.lostPpltn)}</td>
                        <td className="num">{b.walkLostPpltn == null ? "—" : num(b.walkLostPpltn)}</td>
                        <td className="text-[12px] text-ink-2">{b.reasons.map((x) => BANK_REASON_SHORT[x] || x).join(" · ") || "—"}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <p className="text-[14px] text-ink-2">이 지역에 평가한 은행 지점이 없습니다.</p>}
              <p className="mt-3 text-[12px] text-ink-3"><Sents>잃는 주민 = 지금은 2km 안에 그 지점이 있는데, 닫히면 2km 안에 다른 은행도 은행 업무를 하는 우체국도 없는 주민
                (지점마다 따로 닫힌다고 가정). 분석용 기준이며 공식 사전영향평가가 아닙니다.</Sents></p>
            </Card>

            {r.visit && r.visit.days.length > 0 && (
              <Card title="방문 여건 (오늘~모레, 09~18시)">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{r.visit.days.map((d) => (
                  <div key={d.date} className="rounded-[14px] bg-surface p-4">
                    <div className="flex items-center justify-between text-[13px]"><span className="font-medium">{d.dayLabel} {d.date.slice(5).replace("-", ".")}</span>
                      {d.closed ? <span className="badge badge-warn">휴무 · {d.closedReason}</span>
                        : <span className={`badge ${d.level != null ? VISIT_BADGE[d.level] : "badge-info"}`}>{d.label}</span>}</div>
                    <p className="mt-2 text-[13px] text-ink-2">{d.reasons.length ? d.reasons.map((x) => x.text).join(" · ") : "특이 사항 없음"}</p>
                    <p className="mt-1 text-[12px] text-ink-3">{d.tmpMin != null ? `${num(d.tmpMin, 0)}~${num(d.tmpMax, 0)}℃` : ""}{d.pm10 ? ` · 미세먼지 ${d.pm10}` : ""}</p>
                  </div>
                ))}</div>
              </Card>
            )}

            <section className="text-[12px] leading-relaxed text-ink-3">
              <p><Sents>⚠ 이 보고서의 값은 공개 자료로 계산한 분석용 지표이며 공식 통계가 아닙니다. 거리는 직선거리(EPSG:5179) 기준이고, ‘걸어서’ 지표는
                OpenStreetMap 보행 도로망 최단 경로(고령자 0.8m/s, 경사·신호 대기 미반영)입니다. 고령 인구는 KOSIS 주민등록인구, 인구는 통계청 SGIS {r.meta.statYear}년 기준.</Sents></p>
              <p className="mt-1">자료: 우정사업본부 · 통계청 SGIS·KOSIS · 카카오 로컬(은행 지점) · 국립중앙의료원 · 기상청·에어코리아 · OpenStreetMap 기여자(ODbL)</p>
              <p className="no-print mt-2"><Link href={`/?adm=${admCd}`} className="link">지도에서 보기 ›</Link></p>
            </section>
          </>
        )}
      </div>
    </Layout>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card p-4">
      <div className="text-[12px] font-medium text-ink-2">{label}</div>
      <div className="tnum mt-0.5 text-[22px] font-semibold tracking-tight">{value}</div>
      {note && <div className="mt-0.5 text-[12px] text-ink-3">{note}</div>}
    </div>
  );
}
