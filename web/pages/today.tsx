import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useState } from "react";
import type AtlasMapType from "@/components/AtlasMap";
import type { MapLabel } from "@/components/AtlasMap";
import Layout, { Card, ErrorBox, Hero, Segmented, Stat } from "@/components/Layout";
import MapWarmup from "@/components/MapWarmup";
import VisitBadge from "@/components/VisitBadge";
import { api, cachedApi, qs, type AreaFC, type AreaProps, type VisitConditions, type VisitItem } from "@/lib/api";
import { dist, dt, num, NO_DATA, REASON_LABEL, shortSido, VISIT_FILL, VISIT_LABEL } from "@/lib/format";
import { StatSkeletons } from "@/components/Skeleton";
import { useQueryState } from "@/lib/useQueryState";

const AtlasMap = dynamic(() => import("@/components/AtlasMap"), { ssr: false }) as typeof AtlasMapType;
type P = AreaProps & { visit?: VisitItem };

export default function TodayPage() {
  const router = useRouter();
  const [date, setDate] = useQueryState<string>("date", "");   // 비우면 서버가 오늘(운영 끝났으면 내일)을 고름
  const [d, setD] = useState<VisitConditions | null>(null);
  const [fc, setFc] = useState<AreaFC | null>(null);
  const [err, setErr] = useState<{ code?: string; message: string } | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    cachedApi<AreaFC>(`/areas/geojson${qs({ level: 2, metric: "AGED65_FAR_PPLTN" })}`).then(setFc).catch(() => setFc(null));
  }, []);
  useEffect(() => {
    let alive = true;
    setErr(null);
    api<VisitConditions>(`/visit/conditions${qs({ date: date || undefined })}`)
      .then((r) => { if (alive) setD(r); })
      .catch((e) => { if (alive) { setD(null); setErr({ code: e.code, message: e.message }); } });
    return () => { alive = false; };
  }, [date]);

  const byCd = useMemo(() => new Map((d?.items || []).map((x) => [x.admCd, x])), [d]);
  const features = useMemo(() => (fc?.features || []).map((f) => ({ ...f, properties: { ...f.properties, visit: byCd.get(f.properties.admCd) } as P })), [fc, byCd]);
  const styleOf = useCallback((p: P) => {
    const lv = p.visit?.level;
    return { fill: lv === null || lv === undefined ? NO_DATA : VISIT_FILL[lv], opacity: 0.85, stroke: "#ffffff" };
  }, []);
  const tooltipOf = useCallback((p: P) => {
    const v = p.visit;
    if (!v || v.level === null) return "예보 없음";
    const why = v.reasons.length ? v.reasons.map((r) => r.text).join(" · ") : "특이 사항 없음";
    return `방문 여건 <b>${v.label}</b> · ${why}<br/>2km 밖 65세 이상 ${num(v.agedFarPpltn)}명`;
  }, []);

  const risky = (d?.items || []).filter((x) => (x.level ?? 0) >= 1);
  // 먼저 살펴볼 상위 10곳을 지도에 늘 표시 (겹치는 라벨은 지도가 숨김) (마우스를 올리지 않아도 보이게)
  const labels: MapLabel[] = useMemo(() => {
    const pos = new Map((fc?.features || []).map((f) => [f.properties.admCd, f.properties]));
    return risky.slice(0, 10).flatMap((x) => {
      const p = pos.get(x.admCd);
      if (p?.lat == null || p?.lon == null) return [];
      return [{ key: x.admCd, lat: p.lat, lon: p.lon, title: x.admNm, value: x.reasons[0]?.text,
        tone: x.level === 2 ? "bad" as const : "warn" as const }];
    });
  }, [risky, fc]);
  const shown = all ? risky : risky.slice(0, 20);
  const topReason = Object.entries(d?.summary.byReason || {}).sort((a, b) => b[1] - a[1])[0];
  const noData = err?.code === "VISIT_NO_DATA";
  const closed = !!d?.meta.closed;

  return (
    <Layout title="방문 여건">
      <MapWarmup />
      <Hero eyebrow="오늘의 방문 여건" title={<>오늘, 우체국 가는 길은<br className="hidden sm:block" /> 괜찮을까요.</>}
        sub="기상청 단기예보와 에어코리아 미세먼지 예보로 시군구마다 창구 운영 시간(09~18시)의 방문 부담을 판정하고, 우체국에서 멀리 사는 고령인구와 함께 보여 줍니다." />

      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        {noData && <SetupGuide />}
        {err && !noData && <ErrorBox error={err.message} />}
        {!d && !err && <StatSkeletons />}
        {d && (
          <>
            <div className="card flex flex-wrap items-center gap-3 p-4">
              <Segmented ariaLabel="날짜" value={d.meta.date} onChange={(v) => setDate(v)}
                options={d.meta.dates.map((x) => ({ value: x.date,
                  label: `${x.label} ${x.date.slice(5).replace("-", ".")}${x.closed ? " · 휴무" : ""}` }))} />
              <span className="flex-1" />
              <span className="text-[12px] text-ink-3">운영 시간 {d.meta.window} 예보 기준
                {!d.meta.hasCalendar && " · 공휴일 자료 없음(주말만 휴무로 봄)"}</span>
            </div>

            {closed && (
              <div className="card rise flex flex-col gap-4 border border-[#ff9500]/30 p-5 sm:flex-row sm:items-center" role="status">
                <span className="badge badge-warn shrink-0 self-start sm:self-center">창구 휴무</span>
                <div className="min-w-0 flex-1 text-[14px]">
                  <p className="text-[17px] font-semibold">{d.meta.closedReason} — 우체국 금융 창구가 쉽니다</p>
                  <p className="mt-1 text-ink-2">이날은 365코너(ATM)와 공휴일에 여는 약국·의원이 생활 거점입니다.
                    365코너가 없는 읍면동 <b className="whitespace-nowrap text-ink">{num(d.summary.emdWithout365)}곳</b>
                    {d.summary.holidayCareGapPpltn !== null && <>, 2km 안에 공휴일 진료처가 없는 인구 <b className="whitespace-nowrap text-ink">{num(d.summary.holidayCareGapPpltn)}명</b></>}.</p>
                </div>
                <Link href="/hubs" className="btn-ghost shrink-0 self-start whitespace-nowrap no-underline sm:self-center">생활 거점 보기 ›</Link>
              </div>
            )}

            <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="나쁨" value={`${num(d.summary.byLevel["나쁨"])}곳`} tone={d.summary.byLevel["나쁨"] ? "bad" : undefined}
                note={`시군구 ${num(d.summary.areas)}곳 중`} />
              <Stat label="주의" value={`${num(d.summary.byLevel["주의"])}곳`} note={`좋음 ${num(d.summary.byLevel["좋음"])}곳`} />
              <Stat label="먼 곳 고령인구 · 여건 주의 이상" value={`${num(d.summary.atRiskAged)}명`} tone={d.summary.atRiskAged ? "bad" : undefined}
                note="우체국까지 2km 넘는 65세 이상 (KOSIS)" />
              <Stat label="가장 많은 원인" value={topReason ? REASON_LABEL[topReason[0]] || topReason[0] : "없음"}
                note={topReason ? `${num(topReason[1])}개 시군구` : "모든 시군구 여건 좋음"} />
            </div>

            <Card title="시군구별 방문 여건" pad={false}
              right={<span className="flex items-center gap-3 text-[12px] text-ink-2">
                {[0, 1, 2].map((lv) => (
                  <span key={lv} className="flex items-center gap-1.5">
                    <span className="inline-block h-3 w-3 rounded-[4px]" style={{ background: VISIT_FILL[lv] }} />{VISIT_LABEL[lv]}
                  </span>
                ))}
                <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-[4px]" style={{ background: NO_DATA }} />예보 없음</span>
              </span>}>
              <div className="px-3 pb-3">
                <AtlasMap<P> className="h-[480px] overflow-hidden rounded-[14px] md:h-[700px]" features={features} styleOf={styleOf}
                  tooltipOf={tooltipOf} geomKey="sgg" labels={labels} />
                <p className="px-2 pt-2 text-[12px] text-ink-3">지역을 누르면 정보가 고정됩니다 · 라벨은 먼저 살펴볼 지역(겹치면 확대 시 표시) · 표의 행을 누르면 지도 화면으로</p>
              </div>
            </Card>

            <Card title={closed ? "휴무일에 먼저 살펴볼 지역" : "먼저 살펴볼 지역"} pad={false}
              right={<span className="text-[12px] text-ink-3">여건 주의 이상 {num(risky.length)}곳 · 나쁨 먼저, 먼 곳 고령인구 많은 순</span>}>
              {risky.length ? (
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="tbl">
                    <thead className="whitespace-nowrap"><tr><th>지역</th><th>여건</th><th>원인</th><th className="num">기온</th><th className="num">강수</th>
                      <th className="num">2km 밖 65세+</th>
                      {closed ? <><th className="num" title="시군구 안 읍면동 중 365코너가 없는 곳">365코너 없는 읍면동</th><th className="num">공휴일 의료 공백</th></> : <th className="num">최근접 우체국</th>}</tr></thead>
                    <tbody>{shown.map((x) => (
                      <tr key={x.admCd} className="clickable" onClick={() => router.push(`/?adm=${x.admCd}&metric=AGED65_FAR_PPLTN`)}>
                        <td className="whitespace-nowrap"><span className="text-ink-3">{shortSido(x.parentNm)} </span><span className="font-medium">{x.admNm}</span></td>
                        <td className="whitespace-nowrap"><VisitBadge level={x.level} /></td>
                        <td className="min-w-[180px] text-[13px]">{x.reasons.map((r) => r.text).join(" · ")}</td>
                        <td className="num whitespace-nowrap">{num(x.tmpMin, 0)}~{num(x.tmpMax, 0)}℃</td>
                        <td className="num whitespace-nowrap">{x.pcpMm ? `${num(x.pcpMm, 1)}mm` : x.snoCm ? `${num(x.snoCm, 1)}cm` : "—"}</td>
                        <td className="num font-medium">{num(x.agedFarPpltn)}</td>
                        {closed ? <>
                          <td className="num whitespace-nowrap">{x.emdWithout365 == null ? "—" : <><span className={x.emdWithout365 ? "font-medium text-[#a34700]" : ""}>{num(x.emdWithout365)}</span><span className="text-ink-3"> / {num(x.emdCount)}</span></>}</td>
                          <td className="num">{num(x.holidayCareGapPpltn)}</td>
                        </> : <td className="num whitespace-nowrap">{dist(x.nearestFinM)}</td>}
                      </tr>
                    ))}</tbody>
                  </table>
                  {risky.length > shown.length && <button className="link mt-3 px-3" onClick={() => setAll(true)}>{num(risky.length - shown.length)}곳 더 보기 ›</button>}
                </div>
              ) : <p className="px-6 pb-6 text-[15px] text-ink-2">이날은 모든 시군구의 방문 여건이 좋습니다.</p>}
            </Card>

            <Card title="이렇게 판정합니다">
              <div className="grid gap-x-8 gap-y-2 text-[14px] text-ink-2 md:grid-cols-2">
                <p><b className="text-ink">비</b> — 운영 시간에 비가 오면 주의, 합계 30mm 이상이거나 한 시간에 10mm 이상이면 나쁨</p>
                <p><b className="text-ink">눈</b> — 눈·진눈깨비가 오면 주의, 쌓이는 눈이 1cm 이상이면 나쁨(빙판·낙상)</p>
                <p><b className="text-ink">더위</b> — 최고 31℃ 이상 주의, 33℃ 이상 나쁨 (폭염특보 기준 참고)</p>
                <p><b className="text-ink">추위</b> — 최저 -5℃ 이하 주의, -10℃ 이하 나쁨</p>
                <p><b className="text-ink">바람</b> — 풍속 9m/s 이상 주의, 14m/s 이상 나쁨 (강풍주의보 기준 참고)</p>
                <p><b className="text-ink">미세먼지</b> — PM10·PM2.5 예보 ‘나쁨’ 주의, ‘매우나쁨’ 나쁨 (권역 예보)</p>
              </div>
              <p className="mt-4 text-[12px] leading-relaxed text-ink-3">
                ⚠ {d.meta.note} 날씨는 시군구 대표점이 있는 5km 격자 한 곳의 예보입니다. 규칙 {d.meta.ruleVersion} ·
                기상청 발표 {dt(d.meta.weatherBaseAt)} · {d.meta.airAnnouncedAt ? `에어코리아 발표 ${dt(d.meta.airAnnouncedAt)}` : "미세먼지 예보는 아직 이 날짜까지 발표되지 않음"} · 먼 곳 고령인구는 calcRun 기준
                {" "}<Link href="/about/metrics" className="link text-[12px]">지표 정의 ›</Link>
              </p>
            </Card>
          </>
        )}
      </div>
    </Layout>
  );
}

function SetupGuide() {
  return (
    <div className="card mx-auto max-w-lg p-6 text-center">
      <p className="text-[17px] font-semibold">아직 받은 예보가 없습니다</p>
      <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
        공공데이터포털에서 「기상청_단기예보 조회서비스」와 「한국환경공단_에어코리아_대기오염정보」를 활용신청한 뒤,
        일반 인증키(Decoding)를 <code>.env</code> 의 <code>DATA_GO_KR_KEY</code> 에 넣고 실행하세요.
      </p>
      <pre className="mt-3 rounded-[10px] bg-surface p-3 text-[13px]">make weather</pre>
    </div>
  );
}
