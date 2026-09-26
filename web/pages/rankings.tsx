import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Layout, { Card, Empty, ErrorBox, Hero, NoDataGuide, Segmented } from "@/components/Layout";
import { api, cachedApi, qs, type MetricDef, type Region } from "@/lib/api";
import { groupMetrics, num, shortSido, withUnit } from "@/lib/format";
import { TableSkeleton } from "@/components/Skeleton";
import { useQueryState } from "@/lib/useQueryState";

type Row = { admCd: string; admNm: string; parentNm: string | null; value: number | null; rank: number | null;
  rankOf: number | null; percentile: number | null; totPpltn: number | null; agedChildIdx: number | null };
type Resp = { items: Row[]; total: number; metric: { code: string; name: string; unit: string; higherIsWorse: boolean } };

export default function Rankings() {
  const router = useRouter();
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  // 모든 조건을 주소에 반영 (?metric=&level=3&sido=37&sort=asc) — 공유·새로고침에도 같은 순위
  const [metric, setMetric] = useQueryState<string>("metric", "ACCESS_GAP_SCORE");
  const [levelStr, setLevelStr] = useQueryState<"2" | "3">("level", "2", ["2", "3"]);
  const level = Number(levelStr) as 2 | 3;
  const setLevel = (l: 2 | 3) => setLevelStr(String(l) as "2" | "3");
  const [sidoQ, setSido] = useQueryState<string>("sido", "");
  const [sort, setSort] = useQueryState<"desc" | "asc">("sort", "desc", ["desc", "asc"]);
  const [data, setData] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    cachedApi<{ items: MetricDef[] }>("/metrics", 600_000).then((r) => setMetrics(r.items.filter((m) => m.available))).catch(() => null);
    cachedApi<{ items: Region[] }>("/meta/regions", 600_000).then((r) => setRegions(r.items)).catch(() => null);
  }, []);
  const sido = sidoQ || regions.find((r) => r.emdCount > 0)?.admCd || "";

  // 시군구 순위는 시도와 무관 — 시도 목록이 늦게 와 기본 시도가 정해져도 다시 요청하지 않게 요청에 쓰는 값만 의존
  const parent = level === 3 ? sido : "";
  useEffect(() => {
    if (level === 3 && !parent) return;
    setErr(null);
    let alive = true;   // 조건을 빠르게 바꿀 때 이전 응답이 덮어쓰지 않게
    api<Resp>(`/areas${qs({ level, metric, parent: parent || undefined, sort, size: 20 })}`)
      .then((r) => { if (alive) setData(r); }).catch((e) => { if (alive) { setData(null); setErr(e.message); } });
    return () => { alive = false; };
  }, [metric, level, parent, sort]);

  const unit = data?.metric.unit || "";
  const worseFirst = data ? (data.metric.higherIsWorse ? sort === "desc" : sort === "asc") : true;
  const chartData = (data?.items || []).filter((r) => r.value !== null)
    .map((r) => ({ name: level === 3 ? r.admNm : `${r.parentNm ? shortSido(r.parentNm) + " " : ""}${r.admNm}`, value: r.value, admCd: r.admCd }));
  const go = (admCd: string) => router.push(`/?adm=${admCd}&metric=${metric}`);
  const noData = !!err && /CALC_RUN_NOT_FOUND|완료된 계산/.test(err);

  return (
    <Layout title="지역 순위">
      <Hero title="지역 순위." sub="지표를 고르면 전국 시군구(또는 시도 안 읍면동)를 값 순서로 보여 줍니다. 막대나 행을 누르면 지도로 이동합니다." />
      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        <div className="card flex flex-wrap items-center gap-3 p-4">
          <select name="metric" className="field max-w-[280px]" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="지표">
            {groupMetrics(metrics).map((g) => (
              <optgroup key={g.label} label={g.label}>
                {g.items.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}
              </optgroup>
            ))}
          </select>
          <Segmented ariaLabel="단위" value={level} onChange={setLevel}
            options={[{ value: 2, label: "시군구 · 전국" }, { value: 3, label: "읍면동 · 시도 안" }]} />
          {level === 3 && (
            <select name="sido" className="field max-w-[180px]" value={sido} onChange={(e) => setSido(e.target.value)} aria-label="시도">
              {regions.filter((r) => r.emdCount > 0).map((r) => <option key={r.admCd} value={r.admCd}>{r.admNm}</option>)}
            </select>
          )}
          <span className="flex-1" />
          <Segmented ariaLabel="정렬" value={sort} onChange={setSort}
            options={[{ value: "desc", label: "큰 값 20" }, { value: "asc", label: "작은 값 20" }]} />
        </div>
        {err && (noData ? <NoDataGuide /> : <ErrorBox error={err} />)}
        {!data && !err && <div className="card pt-6"><TableSkeleton rows={8} /></div>}
        {data && (
          <>
            <Card title={data.metric.name}
              right={<span className="text-[13px] text-ink-3">{worseFirst ? "접근성 취약 쪽" : "접근성 양호 쪽"} 20곳 · 전체 {data.total.toLocaleString()}곳</span>}>
              {chartData.length ? (
                <div style={{ height: Math.max(chartData.length * 28 + 30, 160) }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} layout="vertical" margin={{ left: 4, right: 28, top: 0, bottom: 0 }} barCategoryGap={5}>
                      <CartesianGrid horizontal={false} stroke="#e8e8ed" />
                      <XAxis type="number" tick={{ fontSize: 12, fill: "#6e6e73" }} axisLine={false} tickLine={false}
                        tickFormatter={(v) => (unit === "m" ? `${num(v / 1000, 1)}km` : num(v, 1))} />
                      <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 13, fill: "#1d1d1f" }} axisLine={false} tickLine={false} />
                      <Tooltip cursor={{ fill: "rgba(0,0,0,.03)" }} contentStyle={{ borderRadius: 12, border: 0, boxShadow: "0 4px 20px rgba(0,0,0,.12)" }}
                        formatter={(v: number) => [withUnit(v, unit), data.metric.name]} />
                      <Bar dataKey="value" fill="#0071e3" radius={[0, 6, 6, 0]} cursor="pointer"
                        onClick={(d: { admCd?: string }) => d.admCd && go(d.admCd)} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <Empty>값이 있는 지역이 없습니다.</Empty>}
            </Card>
            <Card title="표로 보기" pad={false}>
              <div className="overflow-x-auto px-3 pb-3">
                <table className="tbl">
                  <thead><tr><th className="num">순위</th><th>지역</th><th className="num">값</th><th className="num">백분위</th><th className="num">인구</th><th className="num">노령화지수</th></tr></thead>
                  <tbody>
                    {data.items.map((r) => (
                      <tr key={r.admCd} className="clickable" onClick={() => go(r.admCd)}>
                        <td className="num text-ink-3">{r.rank ?? "—"}</td>
                        <td>{r.parentNm ? <span className="text-ink-3">{r.parentNm} </span> : null}<span className="font-medium">{r.admNm}</span></td>
                        <td className="num font-medium">{withUnit(r.value, unit)}</td>
                        <td className="num">{r.percentile ?? "—"}</td>
                        <td className="num">{num(r.totPpltn)}</td>
                        <td className="num">{num(r.agedChildIdx, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </div>
    </Layout>
  );
}
