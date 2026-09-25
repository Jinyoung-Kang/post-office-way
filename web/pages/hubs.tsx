import Link from "next/link";
import { useEffect, useState } from "react";
import Layout, { Card, Empty, ErrorBox, Hero, NoDataGuide, Segmented, Stat } from "@/components/Layout";
import { StatSkeletons, TableSkeleton } from "@/components/Skeleton";
import { api, qs, type HubFacility, type HubSummary, type Page, type Region } from "@/lib/api";
import { dist, dt, num, shortSido } from "@/lib/format";
import { useQueryState } from "@/lib/useQueryState";

type Sort = "soleHub" | "soleFin" | "served";
const SORTS: { value: Sort; label: string }[] = [
  { value: "soleHub", label: "마지막 거점" }, { value: "soleFin", label: "금융 대체 불가" }, { value: "served", label: "담당 인구" },
];
const SIZE = 20;

export default function HubsPage() {
  const [sum, setSum] = useState<HubSummary | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [sido, setSido] = useQueryState<string>("sido", "");
  const [sort, setSort] = useQueryState<Sort>("sort", "soleHub", ["soleHub", "soleFin", "served"]);
  const [pageStr, setPageStr] = useQueryState<string>("page", "1");
  const page = Math.max(1, Number(pageStr) || 1);
  const [list, setList] = useState<Page<HubFacility> | null>(null);
  const [loadingList, setLoadingList] = useState(true);

  useEffect(() => {
    api<HubSummary>("/hubs/summary").then(setSum).catch((e) => setErr(e.message));
    api<{ items: Region[] }>("/meta/regions").then((r) => setRegions(r.items)).catch(() => null);
  }, []);
  useEffect(() => {
    let alive = true;
    setLoadingList(true);
    api<Page<HubFacility>>(`/hubs/facilities${qs({ sido: sido || undefined, sort, page, size: SIZE })}`)
      .then((r) => { if (alive) setList(r); }).catch((e) => { if (alive) { setList(null); setErr(e.message); } })
      .finally(() => { if (alive) setLoadingList(false); });
    return () => { alive = false; };
  }, [sido, sort, page]);

  const noData = !!err && /CALC_RUN_NOT_FOUND|완료된 계산/.test(err);
  const t = sum?.totals;
  const pages = list ? Math.max(1, Math.ceil(list.total / SIZE)) : 1;

  return (
    <Layout title="생활 거점">
      <Hero eyebrow="생활 거점" title={<>우체국이 마지막으로<br className="hidden sm:block" /> 남은 동네.</>}
        sub="약국·의원·은행 지점이 2km 안에 없는 곳에서 우체국은 유일한 생활 거점입니다. 집계구(평균 약 500명)마다 판정해, 닫히면 대신할 곳이 없는 우체국을 찾습니다." />

      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        {err && (noData ? <NoDataGuide /> : <ErrorBox error={err} />)}
        {!sum && !err && <StatSkeletons />}
        {sum && !sum.available && (
          <div className="card mx-auto max-w-lg p-6 text-center">
            <p className="text-[17px] font-semibold">약국·병의원 자료가 아직 계산에 없습니다</p>
            <p className="mt-2 text-[14px] text-ink-2">DATA_GO_KR_KEY 로 국립중앙의료원 자료를 받고 지표를 다시 계산하세요.
              워커가 켜져 있으면 매주 월요일 04:20 에 자동으로 받습니다.</p>
            <pre className="mt-3 rounded-[10px] bg-surface p-3 text-[13px]">make care && make calc</pre>
          </div>
        )}
        {sum?.available && t && (
          <>
            <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="우체국이 마지막 생활 거점인 인구" value={`${num(t.soleHubPpltn)}명`} tone="bad"
                note="2km 안 은행·약국·의원 없이 우체국만" />
              <Stat label="대체할 곳이 없는 우체국" value={`${num(sum.facilities.withSoleHub)}곳`}
                note={`닫히면 생활 거점이 사라지는 주민이 있음 · 담당 ${num(sum.facilities.served)}곳 중`} />
              <Stat label="의료 공백 인구" value={`${num(t.careDesertPpltn)}명`} note="2km 안 약국·의원·보건소 모두 없음" />
              <Stat label="공휴일 의료 공백 인구" value={`${num(t.holidayCareGapPpltn)}명`}
                note="2km 안 공휴일 진료시간이 등록된 약국·의원 없음" />
            </div>
            <div className="rise grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="약국까지 (인구 가중)" value={dist(t.popwPharmacyM)} note={`약국 ${num(sum.care.pharmacy)}곳`} />
              <Stat label="의원·병원까지 (인구 가중)" value={dist(t.popwClinicM)} note={`의원·병원·보건소 ${num(sum.care.clinic)}곳`} />
              <Stat label="생활 서비스 공백 인구" value={`${num(t.lifeDesertPpltn)}명`} note="우체국·은행·약국·의원 모두 2km 밖" />
              <Stat label="공휴일에 여는 곳" value={`${num(sum.care.holidayOpen)}곳`} note={`자료 ${dt(sum.care.asOf)} · 국립중앙의료원`} />
            </div>
          </>
        )}

        <Card title="지켜야 할 우체국" pad={false}
          right={<div className="flex flex-wrap items-center gap-2">
            <select className="field w-auto py-1.5 text-[13px]" value={sido} aria-label="시도"
              onChange={(e) => { setSido(e.target.value); setPageStr("1"); }}>
              <option value="">전국</option>
              {regions.map((r) => <option key={r.admCd} value={r.admCd}>{r.admNm}</option>)}
            </select>
            <Segmented ariaLabel="정렬" value={sort} onChange={(v) => { setSort(v); setPageStr("1"); }} options={SORTS} />
          </div>}>
          <p className="-mt-2 px-6 pb-3 text-[13px] text-ink-2">
            <b className="text-ink">담당 인구</b> 이 우체국이 가장 가까운(2km 안) 집계구 인구 ·
            <b className="text-ink"> 금융 대체 불가</b> 그중 다른 금융 우체국·은행 지점도 2km 안에 없는 인구 ·
            <b className="text-ink"> 마지막 거점</b> 거기에 약국·의원도 없는 인구
          </p>
          {loadingList && !list ? <TableSkeleton /> : list && list.items.length ? (
            <div className="px-3 pb-3" aria-live="polite">
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead className="whitespace-nowrap"><tr><th className="num">순위</th><th>우체국</th><th>지역</th>
                    <th className="num">담당 인구</th><th className="num">금융 대체 불가</th><th className="num">마지막 거점</th><th /></tr></thead>
                  <tbody>{list.items.map((f, i) => (
                    <tr key={f.histId}>
                      <td className="num text-ink-3">{(page - 1) * SIZE + i + 1}</td>
                      <td className="min-w-[200px]"><span className="font-medium">{f.name}</span>
                        <div className="text-[12px] text-ink-3">{f.addr || "—"}</div></td>
                      <td className="whitespace-nowrap">{f.parentNm ? <span className="text-ink-3">{shortSido(f.parentNm)} </span> : null}{f.admNm || "—"}</td>
                      <td className="num">{num(f.servedPpltn)}</td>
                      <td className="num">{num(f.soleFinPpltn)}</td>
                      <td className={`num font-semibold ${f.soleHubPpltn ? "text-[#d70015]" : "text-ink-3"}`}>{num(f.soleHubPpltn)}</td>
                      <td className="whitespace-nowrap text-right">
                        {f.admCd && <Link href={`/?adm=${f.admCd}&metric=POST_SOLE_HUB_PPLTN`} className="link text-[13px]">지도</Link>}
                        <Link href={`/whatif?add=${f.histId}`} className="link ml-3 text-[13px]">What-if ›</Link>
                      </td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="mt-3 flex items-center justify-end gap-2 text-[13px]">
                <span className="text-ink-3">{num(list.total)}곳</span>
                <button className="btn-ghost" disabled={page <= 1} onClick={() => setPageStr(String(page - 1))}>이전</button>
                <span className="tnum">{page} / {pages}</span>
                <button className="btn-ghost" disabled={page >= pages} onClick={() => setPageStr(String(page + 1))}>다음</button>
              </div>
            </div>
          ) : <div className="px-6 pb-6"><Empty>조건에 맞는 우체국이 없습니다.</Empty></div>}
        </Card>

        <div className="grid gap-5 md:grid-cols-2">
          <Card title="마지막 거점 인구가 많은 시군구"
            right={<Link href="/rankings?metric=POST_SOLE_HUB_PPLTN" className="link">전체 순위 ›</Link>}>
            {sum?.topAreas.length ? (
              <ol className="space-y-1">{sum.topAreas.map((r, i) => (
                <li key={r.admCd}>
                  <Link href={`/?adm=${r.admCd}&metric=POST_SOLE_HUB_PPLTN`}
                    className="flex items-center justify-between rounded-[10px] px-2 py-2 text-ink no-underline hover:bg-surface">
                    <span className="flex items-center gap-3"><span className="tnum w-5 text-[13px] font-semibold text-ink-3">{i + 1}</span>
                      <span><span className="text-ink-3">{shortSido(r.parentNm)} </span><span className="font-medium">{r.admNm}</span></span></span>
                    <span className="tnum font-semibold">{num(r.value)}명
                      {r.totPpltn ? <span className="ml-1 text-[12px] font-normal text-ink-3">{num((100 * r.value) / r.totPpltn, 1)}%</span> : null}</span>
                  </Link>
                </li>
              ))}</ol>
            ) : <Empty>자료가 없습니다.</Empty>}
          </Card>
          <Card title="이렇게 판정합니다">
            <ol className="list-decimal space-y-2 pl-5 text-[14px] text-ink-2">
              <li>집계구 대표점마다 가장 가까운 금융 우체국·두 번째 우체국·은행 지점·약국·의원(종합병원·병원·의원·보건소)까지 직선거리를 구합니다.</li>
              <li>우체국은 2km 안에 있는데 은행·약국·의원이 모두 2km 밖이면 <b className="text-ink">우체국이 마지막 생활 거점</b>입니다.</li>
              <li>그 우체국이 가장 가깝고 두 번째 우체국도 2km 밖이면, 닫혔을 때 그 주민은 생활 거점을 모두 잃습니다 → <b className="text-ink">대체 불가</b>.</li>
            </ol>
            <p className="mt-4 text-[12px] leading-relaxed text-ink-3">
              ⚠ 직선거리·집계구 대표점 기준 분석값이며 공식 통계가 아닙니다. 치과·한의원·요양병원은 1차 진료 접근성에서 제외했습니다.
              공휴일 진료는 등록된 진료시간 기준이라 당번 약국과 다를 수 있습니다.
            </p>
          </Card>
        </div>
      </div>
    </Layout>
  );
}
