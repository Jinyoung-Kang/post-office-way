import Link from "next/link";
import { useEffect, useState } from "react";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Layout, { Card, ErrorBox, Hero, NoDataGuide, Stat } from "@/components/Layout";
import { StatSkeletons } from "@/components/Skeleton";
import { fmtPeriod } from "@/components/RegionCard";
import { api, cachedApi, type Overview, type VisitConditions } from "@/lib/api";
import { dist, num, SEQ, shortSido } from "@/lib/format";

export default function OverviewPage() {
  const [d, setD] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [visit, setVisit] = useState<VisitConditions | null | undefined>(undefined);   // undefined = 불러오는 중
  useEffect(() => {
    cachedApi<Overview>("/overview").then(setD).catch((e) => setErr(e.message));
    api<VisitConditions>("/visit/conditions").then(setVisit).catch(() => setVisit(null));   // 예보를 안 받았으면 배너 없음
  }, []);
  const noData = !!err && /CALC_RUN_NOT_FOUND|완료된 계산/.test(err);

  return (
    <Layout title="한눈에">
      <Hero eyebrow="우체국 가는 길" title={<>가장 가까운 우체국까지,<br className="hidden sm:block" /> 얼마나 먼가요.</>}
        sub="전국 우체국 시설과 인구·경계 통계를 공간 결합해, 금융 창구가 있는 우체국까지의 거리를 지역마다 계산했습니다.">
        <Link href="/" className="btn btn-lg no-underline">지도에서 보기</Link>
        <Link href="/whatif" className="link text-[17px]">문을 닫는다면? ›</Link>
      </Hero>

      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        {err && (noData ? <NoDataGuide /> : <ErrorBox error={err} />)}
        {/* 배너 자리를 먼저 잡아 두어 예보가 늦게 와도 아래 숫자가 밀리지 않게 (CLS) */}
        {visit === undefined && !err && <div className={`card ${BANNER_H}`} aria-hidden="true" />}
        {visit && <VisitBanner v={visit} />}
        {!d && !err && <StatSkeletons rows={2} />}
        {d && (
          <>
            <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="금융 가능 우체국" value={`${num(d.finTotal)}곳`} note={`전체 시설 ${num(d.facilityTotal)}곳 중`} />
              <Stat label="인구 가중 평균 거리" value={dist(d.weightedAvgDistM)} note="읍면동 대표점 → 최근접 · 직선" />
              <Stat label="2km 넘게 떨어진 인구" value={`${num(d.farShare, 1)}%`} note={`${num(d.farPpltn)}명 (SGIS)`} />
              {d.kosis ? (
                <Stat label="2km 밖 65세 이상" value={`${num(d.kosis.aged65Far)}명`} tone="bad"
                  note={`고령인구의 ${num(d.kosis.aged65FarShare, 1)}% · KOSIS ${fmtPeriod(d.kosis.refPeriod)}`} />
              ) : (
                <Stat label="2km 밖 65세 이상" value="—" note="KOSIS 키를 넣고 make kosis" />
              )}
            </div>

            {(d.oa || d.finGap || d.road) && (
              <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4">
                {d.oa && <Stat label="2km 밖 인구 · 집계구 기준" value={`${num(d.oa.farShare, 1)}%`}
                  note={`${num(d.oa.farPpltn)}명 · 집계구 ${num(d.oa.count)}곳 인구 가중 ${dist(d.oa.popwDistM)}`} />}
                {d.road && <Stat label="도로로 가면" value={`${dist(d.road.popwRoadM)} · ${num(d.road.popwDriveMin, 0)}분`}
                  note={`직선 ${dist(d.road.popwStraightM)}의 ${num(d.road.popwRoadM / d.road.popwStraightM, 1)}배 · 자동차 · ${num(d.road.areas)}곳`} />}
                {d.finGap && <Stat label="우체국만 있는 인구" value={`${num(d.finGap.postOnlyPpltn)}명`}
                  note="2km 안 대면 금융 창구가 우체국뿐 (은행·금고 없음)" />}
                {d.finGap && <Stat label="금융 공백 인구" value={`${num(d.finGap.desertPpltn)}명`} tone="bad"
                  note="2km 안에 우체국도 은행·금고 지점도 없음" />}
              </div>
            )}

            {d.life && (
              <Link href="/hubs" className="card rise grid grid-cols-2 gap-4 p-5 text-ink no-underline hover:bg-white/90 md:grid-cols-4">
                <div className="col-span-2 md:col-span-4 flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-ink-2">생활 거점 — 약국·의원·은행과 함께 본 우체국</span>
                  <span className="link text-[14px]">자세히 ›</span>
                </div>
                <MiniStat label="우체국이 마지막 생활 거점인 인구" value={`${num(d.life.soleHubPpltn)}명`} bad />
                <MiniStat label="대체할 곳이 없는 우체국" value={`${num(d.life.soleHubFacilities)}곳`} />
                <MiniStat label="의료 공백 인구" value={`${num(d.life.careDesertPpltn)}명`} />
                <MiniStat label="공휴일 의료 공백 인구" value={`${num(d.life.holidayCareGapPpltn)}명`} />
              </Link>
            )}

            <Card title="최근접 금융 우체국까지 거리별 인구" right={<span className="text-[12px] text-ink-3">{num(d.areaCount)}개 읍면동 · 인구 비율</span>}>
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={d.distanceBands} margin={{ top: 24, right: 8, left: 8, bottom: 0 }} barCategoryGap="22%">
                    <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 13, fill: "#6e6e73" }} />
                    <YAxis hide domain={[0, "dataMax"]} />
                    <Tooltip cursor={{ fill: "rgba(0,0,0,.03)" }} contentStyle={{ borderRadius: 12, border: 0, boxShadow: "0 4px 20px rgba(0,0,0,.12)" }}
                      formatter={(v: number, _n, p) => [`${num(v, 1)}% · ${num(p.payload.ppltn)}명${p.payload.aged65 !== null ? ` (65+ ${num(p.payload.aged65)}명)` : ""}`, "인구"]} />
                    <Bar dataKey="share" radius={[8, 8, 0, 0]}>
                      {d.distanceBands.map((b, i) => <Cell key={b.label} fill={SEQ[Math.min(i, SEQ.length - 1)]} />)}
                      <LabelList dataKey="share" position="top" formatter={(v: number) => `${num(v, 1)}%`}
                        style={{ fontSize: 13, fontWeight: 600, fill: "#1d1d1f" }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 overflow-x-auto">
                <table className="tbl">
                  <thead><tr><th>거리</th><th className="num">읍면동</th><th className="num">인구</th><th className="num">65세 이상</th></tr></thead>
                  <tbody>{d.distanceBands.map((b) => (
                    <tr key={b.label}><td>{b.label}</td><td className="num">{num(b.areas)}</td><td className="num">{num(b.ppltn)}</td><td className="num">{num(b.aged65)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </Card>

            <div className="grid gap-5 md:grid-cols-2">
              <TopList title="접근성 취약 점수 상위 시군구" unit="점" items={d.topGap} metric="ACCESS_GAP_SCORE" digits={1} />
              {d.topAgedFar.length > 0
                ? <TopList title="2km 밖 고령인구가 많은 시군구" unit="명" items={d.topAgedFar} metric="AGED65_FAR_PPLTN" />
                : <Card title="2km 밖 고령인구"><p className="text-[14px] text-ink-2">KOSIS 주민등록인구를 적재하면 표시됩니다.</p></Card>}
            </div>

            {(d.topPostOnly.length > 0 || d.topSoleHub.length > 0) && (
              <div className="grid gap-5 md:grid-cols-2">
                {d.topPostOnly.length > 0 && <TopList title="우체국이 유일한 금융 창구인 인구가 많은 시군구" unit="명" items={d.topPostOnly} metric="POST_ONLY_PPLTN" />}
                {d.topSoleHub.length > 0 && <TopList title="우체국이 마지막 생활 거점인 인구가 많은 시군구" unit="명" items={d.topSoleHub} metric="POST_SOLE_HUB_PPLTN" />}
              </div>
            )}

            <Card title="시설 구성">
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
                {d.facilities.map((f) => (
                  <div key={f.postDiv} className="flex items-baseline justify-between border-b border-line pb-2 text-[14px]">
                    <span className="text-ink-2">{f.label}</span>
                    <span className="tnum font-semibold">{num(f.count)}{f.finCount ? <span className="ml-1 text-[12px] font-normal text-ink-3">금융 {num(f.finCount)}</span> : null}</span>
                  </div>
                ))}
              </div>
            </Card>
          </>
        )}
      </div>
    </Layout>
  );
}

function MiniStat({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div>
      <div className="text-[12px] text-ink-2">{label}</div>
      <div className={`tnum text-[22px] font-semibold tracking-tight ${bad ? "text-[#d70015]" : ""}`}>{value}</div>
    </div>
  );
}

function TopList({ title, items, unit, metric, digits = 0 }: {
  title: string; unit: string; metric: string; digits?: number;
  items: { admCd: string; admNm: string; parentNm: string | null; value: number }[];
}) {
  return (
    <Card title={title} right={<Link href={`/rankings?metric=${metric}`} className="link">전체 순위 ›</Link>}>
      <ol className="space-y-1">
        {items.map((r, i) => (
          <li key={r.admCd}>
            <Link href={`/?adm=${r.admCd}&metric=${metric}`}
              className="flex items-center justify-between rounded-[10px] px-2 py-2 text-ink no-underline hover:bg-surface">
              <span className="flex items-center gap-3">
                <span className="tnum w-5 text-[13px] font-semibold text-ink-3">{i + 1}</span>
                <span><span className="text-ink-3">{shortSido(r.parentNm)} </span><span className="font-medium">{r.admNm}</span></span>
              </span>
              <span className="tnum font-semibold">{num(r.value, digits)}{unit}</span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}

const BANNER_H = "min-h-[124px] md:min-h-[54px]";   // 휴무 배지까지 들어간 배너 높이 (모바일은 줄바꿈)

function VisitBanner({ v }: { v: VisitConditions }) {
  const cur = v.meta.dates.find((x) => x.date === v.meta.date);
  const day = cur?.label || v.meta.date;
  const bad = v.summary.byLevel["나쁨"] || 0, warn = v.summary.byLevel["주의"] || 0;
  return (
    <Link href="/today" className={`card rise flex flex-wrap content-center items-center gap-x-4 gap-y-1 p-4 text-ink no-underline hover:bg-white/90 ${BANNER_H}`}>
      <span className="text-[13px] font-semibold text-ink-2">{day}의 방문 여건</span>
      {v.meta.closed && <span className="badge badge-warn">창구 휴무 · {v.meta.closedReason}</span>}
      <span className="text-[15px]">
        {bad || warn ? <>나쁨 <b className="text-[#d70015]">{num(bad)}곳</b> · 주의 <b>{num(warn)}곳</b>
          {v.summary.atRiskAged > 0 && <> · 우체국에서 먼 65세 이상 <b>{num(v.summary.atRiskAged)}명</b></>}</>
          : "전국 시군구 모두 좋음"}
      </span>
      <span className="link ml-auto text-[14px]">자세히 ›</span>
    </Link>
  );
}
