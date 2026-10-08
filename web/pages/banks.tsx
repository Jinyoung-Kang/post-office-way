import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type AtlasMapType from "@/components/AtlasMap";
import type { Marker } from "@/components/AtlasMap";
import Layout, { Card, Empty, ErrorBox, Hero, NoDataGuide, Segmented, Stat } from "@/components/Layout";
import MapWarmup from "@/components/MapWarmup";
import { TableSkeleton } from "@/components/Skeleton";
import { api, cachedApi, qs, type BankImpact, type BankImpactDetail, type BankImpactList, type CatchmentProps,
  type Feature, type Region } from "@/lib/api";
import { BANK_REASON_SHORT, dist, dt, GRADE_BADGE, GRADE_LABEL, num, shortSido, walkMin } from "@/lib/format";
import { useQueryState } from "@/lib/useQueryState";

const AtlasMap = dynamic(() => import("@/components/AtlasMap"), { ssr: false }) as typeof AtlasMapType;

type Grade = "" | "HIGH" | "MID" | "LOW";
type Sort = "lost" | "catch" | "aged" | "walk" | "far";
const SORTS: { value: Sort; label: string }[] = [
  { value: "lost", label: "대체 창구를 잃는 주민 많은 순" }, { value: "walk", label: "걸어서 잃는 주민 많은 순" },
  { value: "catch", label: "이용 주민 많은 순" }, { value: "aged", label: "65세 이상 많은 순" },
  { value: "far", label: "같은 은행 다음 지점이 먼 순" },
];
const SIZE = 20;
const ALT_LABEL: Record<string, string> = { SAME_BANK: "같은 은행 다음 지점", OTHER_BANK: "다른 은행", POST: "우체국 (은행 업무)" };
const ALT_SHORT: Record<string, string> = { SAME_BANK: "같은 은행", OTHER_BANK: "다른 은행", POST: "우체국" };
// 닫혔을 때 대체 창구까지 거리 — 순차(초록→빨강) 대신 한 색조의 밝기로, 범례와 함께
const ALT_BANDS = [
  { max: 1000, fill: "#cfe3f7", label: "1km 안" }, { max: 2000, fill: "#8fbde9", label: "1~2km" },
  { max: 5000, fill: "#4f8fd1", label: "2~5km" }, { max: Infinity, fill: "#1f4e8c", label: "5km 밖·없음" },
];

export default function BanksPage() {
  const [regions, setRegions] = useState<Region[]>([]);
  const [sido, setSido] = useQueryState<string>("sido", "");
  const [grade, setGrade] = useQueryState<Grade>("grade", "", ["", "HIGH", "MID", "LOW"]);
  const [sort, setSort] = useQueryState<Sort>("sort", "lost", ["lost", "catch", "aged", "walk", "far"]);
  const [pageStr, setPageStr] = useQueryState<string>("page", "1");
  const [id, setId] = useQueryState<string>("id", "");
  const page = Math.max(1, Number(pageStr) || 1);
  const [list, setList] = useState<BankImpactList | null>(null);
  const [detail, setDetail] = useState<BankImpactDetail | null>(null);
  const [geo, setGeo] = useState<Feature<CatchmentProps>[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    cachedApi<{ items: Region[] }>("/meta/regions", 600_000).then((r) => setRegions(r.items)).catch(() => null);
  }, []);

  useEffect(() => {
    let alive = true;   // 조건을 빠르게 바꿀 때 이전 응답이 덮어쓰지 않게
    setLoading(true);
    api<BankImpactList>(`/banks/impact${qs({ sido: sido || undefined, grade: grade || undefined, sort, page, size: SIZE })}`)
      .then((r) => { if (alive) { setList(r); setErr(null); } })
      .catch((e) => { if (alive) { setList(null); setErr(e.message); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [sido, grade, sort, page]);

  // 지점을 고르지 않았으면 목록 1위를 보여 줌(주소에는 남기지 않음)
  const selected = id || list?.items[0]?.placeId || "";
  useEffect(() => {
    if (!selected) { setDetail(null); setGeo([]); return; }
    let alive = true;
    Promise.all([
      api<BankImpactDetail>(`/banks/impact/${encodeURIComponent(selected)}`),
      api<{ features: Feature<CatchmentProps>[] }>(`/banks/impact/${encodeURIComponent(selected)}/geojson`),
    ]).then(([d, g]) => { if (alive) { setDetail(d); setGeo(g.features); } })
      .catch((e) => { if (alive) { setDetail(null); setGeo([]); setErr(e.message); } });
    return () => { alive = false; };
  }, [selected]);

  const pick = (b: BankImpact) => {
    setId(b.placeId);
    if (window.matchMedia("(max-width: 1023px)").matches) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const noData = !!err && /CALC_RUN_NOT_FOUND|BANK_IMPACT_NOT_FOUND|완료된 계산/.test(err);
  const sm = list?.summary;
  const pages = list ? Math.max(1, Math.ceil(list.total / SIZE)) : 1;
  // 등급 버튼 글자는 고정 — 개수를 붙이면 자료가 온 뒤 버튼이 넓어져 화면이 밀림(CLS). 개수는 위 통계 카드에
  const gradeOpts: { value: Grade; label: string }[] = [
    { value: "", label: "전체" }, { value: "HIGH", label: "영향 높음" }, { value: "MID", label: "보통" }, { value: "LOW", label: "낮음" },
  ];

  return (
    <Layout title="은행 지점">
      <MapWarmup />
      <Hero wide eyebrow="은행 지점 영향평가" title="은행 지점"
        sub="은행 지점마다 그 지점이 가장 가까운 주민을 찾고, 문을 닫으면 다른 은행이나 은행 업무를 하는 우체국까지 얼마나 멀어지는지 계산합니다. 2026년 개정된 은행 점포폐쇄 공동절차를 참고한 분석용 평가입니다." />

      <div className="mx-auto max-w-wide space-y-5 px-4 pb-20">
        {err && !list && (noData ? <NoDataGuide /> : <ErrorBox error={err} />)}
        {/* 불러오는 동안에도 같은 카드(값만 —)를 그려 높이를 맞춤 — 자리 표시와 실제 카드 높이가 달라 아래 목록이 밀렸음(CLS 0.088) */}
        {!(err && !list) && (
          <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4" aria-busy={!sm}>
            <Stat label={sido ? "평가한 은행 지점 (선택 지역)" : "평가한 은행 지점"} value={sm ? `${num(sm.branches)}곳` : "—"}
              note="전수 수집 기준 · 새마을금고·저축은행 제외" />   {/* 수집 시각은 상세 아래 '자료'에 — 글이 길어지면 모바일에서 줄이 늘어 아래가 밀림 */}
            <Stat label="영향 높음" value={sm ? `${num(sm.high)}곳` : "—"} tone={sm ? "bad" : undefined}
              note={sm ? `보통 ${num(sm.mid)} · 낮음 ${num(sm.low)}` : "보통 — · 낮음 —"} />
            <Stat label="새로 2km 안 대체 창구를 잃는 주민" value={sm ? `${num(sm.lostPpltn)}명` : "—"}
              note="지점마다 따로 닫힌다고 할 때의 합" />
            <Stat label="걸어서 30분 기준" value={sm && list?.walk ? `${num(sm.walkLostPpltn)}명` : "—"}
              note={!sm || list?.walk ? "고령자 0.8m/s · OSM 도로망" : "도보 계산 전 (make osm)"} />
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_460px]">
          <Card title="은행 지점" pad={false}
            right={<div className="flex flex-wrap items-center gap-2">
              {/* 너비 고정 — 시도 목록이 늦게 오면 선택 상자가 넓어지며 머리글이 줄바꿈돼 아래가 밀렸음(CLS) */}
              <select name="sido" className="field w-34 py-1.5 text-[13px]" value={sido} aria-label="시도"
                onChange={(e) => { setSido(e.target.value); setPageStr("1"); setId(""); }}>
                <option value="">전국</option>
                {regions.map((r) => <option key={r.admCd} value={r.admCd}>{r.admNm}</option>)}
              </select>
              <select name="sort" className="field w-56 py-1.5 text-[13px]" value={sort} aria-label="정렬"
                onChange={(e) => { setSort(e.target.value as Sort); setPageStr("1"); setId(""); }}>
                {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>}>
            <div className="-mt-2 flex flex-wrap items-center gap-2 px-6 pb-3">
              <Segmented ariaLabel="영향 등급" value={grade} onChange={(v) => { setGrade(v); setPageStr("1"); setId(""); }}
                options={gradeOpts} />
            </div>
            {loading && !list ? <TableSkeleton /> : list && list.items.length ? (
              <div className="px-3 pb-3" aria-live="polite">
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead className="whitespace-nowrap"><tr><th className="num">순위</th><th>지점</th><th>지역</th>
                      <th className="num">이용 주민</th><th className="num">잃는 주민</th><th className="num">걸어서</th><th>영향</th></tr></thead>
                    <tbody>{list.items.map((b, i) => (
                      // 고른 행은 배경 대신 왼쪽 파란 막대 — 배경을 칠하면 등급 배지 글자 대비가 4.5:1 아래로 떨어짐
                      <tr key={b.placeId} className={`clickable ${b.placeId === selected ? "shadow-[inset_3px_0_0_#0071e3]" : ""}`}
                        onClick={() => pick(b)}>
                        <td className="num text-ink-3">{(page - 1) * SIZE + i + 1}</td>
                        <td className="min-w-[180px]">
                          <button type="button" className="text-left font-medium" aria-current={b.placeId === selected ? "true" : undefined}
                            onClick={(e) => { e.stopPropagation(); pick(b); }}>
                            {b.name}</button>
                          <div className="text-[12px] text-ink-3">{b.brand || "—"}</div></td>
                        <td className="whitespace-nowrap">{b.parentNm ? <span className="text-ink-3">{shortSido(b.parentNm)} </span> : null}{b.admNm || "—"}</td>
                        <td className="num">{num(b.catchPpltn)}</td>
                        <td className={`num font-semibold ${b.lostPpltn ? "text-[#d70015]" : "text-ink-3"}`}>{num(b.lostPpltn)}</td>
                        <td className="num">{b.walkLostPpltn == null ? "—" : num(b.walkLostPpltn)}</td>
                        <td><span className={`badge ${GRADE_BADGE[b.grade]}`}>{GRADE_LABEL[b.grade]}</span></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <div className="mt-3 flex items-center justify-end gap-2 text-[13px]">
                  <span className="text-ink-3">{num(list.total)}곳</span>
                  <button className="btn-ghost" disabled={page <= 1} onClick={() => { setPageStr(String(page - 1)); setId(""); }}>이전</button>
                  <span className="tnum">{page} / {pages}</span>
                  <button className="btn-ghost" disabled={page >= pages} onClick={() => { setPageStr(String(page + 1)); setId(""); }}>다음</button>
                </div>
              </div>
            ) : <div className="px-6 pb-6"><Empty>조건에 맞는 지점이 없습니다.</Empty></div>}
          </Card>

          <div ref={detailRef} className="space-y-5 lg:sticky lg:top-[64px] lg:self-start">
            {detail ? <Detail d={detail} geo={geo} /> : <div className="card p-6"><TableSkeleton rows={6} /></div>}
          </div>
        </div>

        {list && (
          <Card title="이렇게 판정합니다">
            <ol className="list-decimal space-y-2 pl-5 text-[14px] text-ink-2">
              <li>집계구(평균 약 500명)마다 가장 가까운 <b className="text-ink">은행 지점</b>을 찾아, 그 지점의 이용 주민으로 봅니다.</li>
              <li>그 지점이 닫히면 <b className="text-ink">다음으로 가까운 다른 은행 지점</b>과 <b className="text-ink">은행 업무를 하는 우체국</b> 중 가까운 곳이 대체 창구입니다.</li>
              <li><b className="text-ink">잃는 주민</b>: 지금은 2km 안에 이 지점이 있는데, 닫히면 2km 안에 대체 창구가 없는 주민. 걸어서는 고령자 속도로 30분.</li>
            </ol>
            <ul className="mt-3 space-y-1 text-[13px] text-ink-2">
              {Object.entries(list.reasons).map(([k, v]) => <li key={k}><span className="badge badge-info mr-2">{BANK_REASON_SHORT[k] || k}</span>{v}</li>)}
            </ul>
            <p className="mt-4 text-[12px] leading-relaxed text-ink-3">⚠ {list.rule} {list.banks.assumption}
              {" "}은행 지점은 카카오 장소 전수 수집 기준이며 공식 점포 목록이 아닙니다. 고령 인구는 읍면동 고령 비율로 추정했습니다.</p>
          </Card>
        )}
      </div>
    </Layout>
  );
}

function bandOf(m: number | null) {
  return ALT_BANDS.find((b) => (m ?? Infinity) <= b.max) || ALT_BANDS[ALT_BANDS.length - 1];
}

function Detail({ d, geo }: { d: BankImpactDetail; geo: Feature<CatchmentProps>[] }) {
  const b = d.item;
  // 지도에는 종류마다 가장 가까운 한 곳만 (이 지점은 빨강, 대체 창구는 초록 핀)
  const markers: Marker[] = useMemo(() => [
    { lat: b.lat, lon: b.lon, label: "이 지점", tone: "removed" as const },
    ...(["SAME_BANK", "OTHER_BANK", "POST"] as const)
      .map((k) => d.alternatives.find((a) => a.kind === k))
      .filter((a): a is NonNullable<typeof a> => !!a)
      .map((a) => ({ lat: a.lat, lon: a.lon, label: ALT_SHORT[a.kind], tone: "new" as const })),   // 거리는 아래 목록에
  ], [b, d.alternatives]);
  const maxBand = Math.max(1, ...d.altBands.map((x) => x.ppltn));
  const agedPct = b.catchAged != null && b.catchPpltn ? (100 * b.catchAged) / b.catchPpltn : null;
  return (
    <>
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[19px] font-semibold tracking-tight">{b.name}</h2>
            <p className="text-[13px] text-ink-3">{b.brand} · {b.addr || "—"}</p>
          </div>
          <span className={`badge shrink-0 ${GRADE_BADGE[b.grade]}`}>영향 {GRADE_LABEL[b.grade]}</span>
        </div>
        {b.reasons.length > 0 && (
          <ul className="mt-3 space-y-1 text-[13px] text-ink-2">{b.reasons.map((r) => <li key={r}>• {d.reasons[r] || r}</li>)}</ul>
        )}
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
          <div><dt className="text-ink-3">이용 주민</dt><dd className="tnum text-[17px] font-semibold">{num(b.catchPpltn)}명</dd>
            <dd className="text-[12px] text-ink-3">집계구 {num(b.catchOa)}곳{agedPct != null ? ` · 65세 이상 ${num(agedPct, 0)}%` : ""}</dd></div>
          <div><dt className="text-ink-3">새로 잃는 주민 (2km)</dt>
            <dd className={`tnum text-[17px] font-semibold ${b.lostPpltn ? "text-[#d70015]" : ""}`}>{num(b.lostPpltn)}명</dd>
            <dd className="text-[12px] text-ink-3">{b.lostAged != null ? `65세 이상 약 ${num(b.lostAged)}명` : " "}</dd></div>
          <div><dt className="text-ink-3">평균 거리 (직선)</dt>
            <dd className="tnum font-semibold">{dist(b.popwNowM)} → {dist(b.popwAltM)}</dd>
            <dd className="text-[12px] text-ink-3">지금 → 닫히면 가장 가까운 대체 창구</dd></div>
          <div><dt className="text-ink-3">걸어서 (고령자)</dt>
            <dd className="tnum font-semibold">{b.walkNowM != null ? `${walkMin(b.walkNowM)} → ${b.walkAltM != null ? walkMin(b.walkAltM) : "1시간+"}` : "—"}</dd>
            <dd className="text-[12px] text-ink-3">{b.walkLostPpltn != null ? `30분 안 대체 없어지는 주민 ${num(b.walkLostPpltn)}명` : "도보 계산 전"}</dd></div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          {b.admCd && <Link href={`/report/${b.admCd}`} className="link">{b.admNm} 지역 보고서 ›</Link>}
          {b.admCd && <Link href={`/?adm=${b.admCd}&metric=FIN_DESERT_PPLTN`} className="link">지도에서 보기 ›</Link>}
        </div>
      </Card>

      <div className="card overflow-hidden">
        <AtlasMap<CatchmentProps> className="h-[360px]" features={geo} geomKey={b.placeId} markers={markers} pinOnClick
          styleOf={(p) => ({ fill: bandOf(p.altM).fill, opacity: 0.75 })}
          tooltipOf={(p) => `주민 ${num(p.ppltn)}명 · 지금 ${dist(p.nowM)}<br/>닫히면 ${p.altM != null ? dist(p.altM) : "대체 창구 없음(20km+)"}`}
          padding={[40, 30, 30, 30]} />
        <div className="flex flex-wrap items-center gap-3 px-4 py-2 text-[12px] text-ink-2" aria-label="범례">
          <span className="font-medium">닫히면 대체 창구까지</span>
          {ALT_BANDS.map((x) => <span key={x.label} className="inline-flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-[3px]" style={{ background: x.fill }} />{x.label}</span>)}
        </div>
      </div>

      <Card title="대체 창구">
        <ul className="space-y-1.5 text-[14px]">{d.alternatives.map((a, i) => (
          <li key={`${a.kind}-${i}`} className="flex items-baseline justify-between gap-3">
            <span className="min-w-0"><span className="text-[12px] text-ink-3">{ALT_LABEL[a.kind]}</span>
              <span className="block truncate">{a.name}</span></span>
            <span className="tnum shrink-0 font-medium">{dist(a.distM)}</span>
          </li>
        ))}</ul>
        {!b.postAgent && <p className="mt-2 text-[12px] text-ink-3">이 은행은 우체국 입출금 대상이 아니라고 보고 우체국을 대체 창구에서 뺐습니다.</p>}
        <p className="group-label mt-5">닫히면 대체 창구까지 — 이용 주민</p>
        <div className="space-y-1.5">{d.altBands.map((x) => (
          <div key={x.label} className="grid grid-cols-[84px_1fr_88px] items-center gap-2 text-[13px]">
            <span className="text-ink-2">{x.label}</span>
            <span className="h-2.5 rounded-full bg-surface"><span className="block h-2.5 rounded-full bg-[#4f8fd1]"
              style={{ width: `${(100 * x.ppltn) / maxBand}%` }} /></span>
            <span className="tnum text-right">{num(x.ppltn)}명</span>
          </div>
        ))}</div>
        <p className="mt-4 text-[12px] text-ink-3">
          자료: 은행 지점 전수 수집 {dt(d.banks.fullCrawlAt)}{d.walk?.osmLastModified ? ` · OSM 도로망 ${d.walk.osmLastModified.slice(5, 16)}` : ""}
          {" "}· calcRun {d.meta.calcRunId.slice(0, 8)} · 지도 © OpenStreetMap 기여자(도보 경로)</p>
      </Card>
    </>
  );
}
