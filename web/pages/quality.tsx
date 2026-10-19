import { useState } from "react";
import Layout, { Card, Empty, ErrorBox, Hero, Segmented } from "@/components/Layout";
import { tableView, useApi } from "@/hooks/useApi";
import { TableSkeleton } from "@/components/Skeleton";
import { qs, type Page } from "@/lib/api";
import { dt, num, short } from "@/lib/format";
import JobsPanel from "@/components/JobsPanel";
import ErrorLog from "@/components/ErrorLog";
import Sents from "@/components/Sents";

type Check = { code: string; severity: string; count: number; description: string };
type Block = { scope: string; runId: string; kind: string; status: string; checkedAt: string; checks: Check[] };
type Summary = { runs: Block[]; errorCount: number };
type Issue = { issueId: number; collectRunId: string | null; calcRunId: string | null; checkCode: string; severity: string;
  targetTable: string; targetKey: string; detail: Record<string, unknown>; createdAt: string };
type CollectRun = { collectRunId: string; kind: string; status: string; scope: string; startedAt: string;
  finishedAt: string | null; stats: Record<string, unknown>; error: string | null };
type CalcRun = { calcRunId: string; statYear: number; status: string; createdAt: string; finishedAt: string | null;
  stats: { areas?: number; facilities?: number; elapsedMs?: number }; error: string | null };

const KIND_LABEL: Record<string, string> = {
  POST_AREA: "우체국 시설", POST_DISCOVER: "지역코드 탐색", SGIS_POP: "SGIS 인구", SGIS_BND: "SGIS 경계",
  KOSIS_POP: "KOSIS 주민등록인구", CALC: "지표 계산", SGIS_OA: "SGIS 집계구", KAKAO_GEO: "주소 좌표 검증",
  KAKAO_BANK: "은행·금고 지점", KAKAO_ROAD: "도로 거리", KMA_FCST: "기상청 단기예보", AIR_FCST: "에어코리아 예보",
  NMC_CARE: "약국·병의원", KASI_HOLIDAY: "공휴일(특일)", MOIS_MIGR: "인구이동(행안부)",
};
const KIND_ORDER = ["POST_AREA", "SGIS_POP", "SGIS_BND", "SGIS_OA", "KOSIS_POP", "MOIS_MIGR", "KAKAO_GEO", "KAKAO_BANK", "KAKAO_ROAD", "KMA_FCST", "AIR_FCST", "NMC_CARE", "KASI_HOLIDAY", "CALC"];
const SEV: Record<string, string> = { ERROR: "badge-error", WARN: "badge-warn", INFO: "badge-info" };
const STATUS: Record<string, string> = { DONE: "badge-good", PARTIAL: "badge-warn", FAILED: "badge-error", RUNNING: "badge-info" };
const DETAIL_LABEL: Record<string, string> = {
  name: "이름", admNm: "지역", areaCode: "지역코드", lat: "위도", lon: "경도", method: "방법", postDiv: "구분",
  field: "필드", value: "값", modDt: "수정일", loaded: "적재", totalCount: "totalCount", level: "레벨",
  totPpltn: "총인구", agedChildIdx: "노령화지수", error: "오류", page: "페이지", status: "HTTP", reason: "사유",
  distM: "거리(m)", addr: "주소", emdCd: "읍면동", missing: "없음", part: "부분",
  sidoNm: "시도", ctpvNm: "시도", sggNm: "시군구", refYm: "기준월", moisCd: "행안부 코드", months: "달 수",
};

export default function Quality() {
  const [filter, setFilter] = useState<{ run?: Block; code?: string; severity?: string; scope: "latest" | "all"; page: number }>({ scope: "latest", page: 1 });
  // 머리글 배지와 같은 요청을 하나로 (운영 화면이라 짧게)
  const sumQ = useApi<Summary>("/dq/summary", { cacheMs: 5_000 });
  const sum = sumQ.data;
  // 받는 중·실패를 빈 표로 보이지 않게 — 받는 중은 자리 표시, 실패는 오류 상자 (tableView)
  const runsQ = useApi<Page<CollectRun>>("/meta/collect-runs?size=12");
  const calcsQ = useApi<Page<CalcRun>>("/meta/calc-runs?size=5");
  const runs = runsQ.data?.items ?? [];
  const calcs = calcsQ.data?.items ?? [];
  const sel = filter.run;
  const issuesQ = useApi<Page<Issue>>(`/dq/issues${qs({ collectRunId: sel?.scope === "collect" ? sel.runId : undefined,
    calcRunId: sel?.scope === "calc" ? sel.runId : undefined, checkCode: filter.code, severity: filter.severity,
    scope: filter.scope, page: filter.page, size: 30 })}`);
  const issues = issuesQ.data;
  const issuesView = tableView(issuesQ, (d) => d.items.length);
  const err = (sumQ.error ?? issuesQ.error)?.message ?? null;

  return (
    <Layout title="데이터·운영">
      <Hero title="데이터·운영" sub="작업 큐가 무엇을 언제 실행했는지, 수집·계산마다 어떤 품질 규칙에 걸렸는지 봅니다. 0건인 규칙도 ‘실행했음’으로 기록됩니다." />
      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        <ErrorLog clientErrors={err ? [err] : []} />
        <JobsPanel />
        {sum && sum.errorCount > 0 && (
          <div className="card flex items-center gap-3 p-4 text-[14px]">
            <span className="badge badge-error">ERROR</span>
            <span>최신 수집·계산에서 심각도 ERROR 규칙에 걸린 행이 <b>{num(sum.errorCount)}건</b> 있습니다.</span>
            <button className="link ml-auto" onClick={() => setFilter({ scope: "latest", severity: "ERROR", page: 1 })}>보기 ›</button>
          </div>
        )}

        <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-2">
          {[...(sum?.runs || [])].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)).map((b) => (
            <Card key={b.runId} title={KIND_LABEL[b.kind] || b.kind}
              right={<span className="flex items-center gap-2 text-[12px] text-ink-3"><span className={`badge ${STATUS[b.status] || "badge-info"}`}>{b.status}</span>{dt(b.checkedAt)}</span>}>
              <div className="-mx-2">
                {b.checks.map((c) => (
                  <button key={c.code} onClick={() => setFilter({ run: b, code: c.code, scope: "latest", page: 1 })}
                    className="flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left hover:bg-surface">
                    <span className={`badge ${SEV[c.severity]} w-[46px] justify-center`}>{c.severity}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium">{c.description}</span>
                      <span className="block font-mono text-[11px] text-ink-3">{c.code}</span>
                    </span>
                    <span className={`tnum text-[15px] font-semibold ${c.count === 0 ? "text-ink-3" : ""}`}>{num(c.count)}</span>
                  </button>
                ))}
                {!b.checks.length && <p className="px-2 text-[13px] text-ink-3">기록된 검사가 없습니다.</p>}
              </div>
            </Card>
          ))}
        </div>
        {sum && !sum.runs.length && <Empty><Sents>아직 수집 기록이 없습니다. <code>make all-data</code> 를 실행하세요.</Sents></Empty>}

        <Card title="이슈" pad={false} right={
          <div className="flex flex-wrap items-center gap-2">
            {(filter.run || filter.code) && (
              <span className="badge badge-info">{filter.run ? KIND_LABEL[filter.run.kind] || filter.run.kind : ""} {filter.code || ""}</span>
            )}
            <select name="severity" className="field w-auto py-1.5 text-[13px]" value={filter.severity || ""} aria-label="심각도"
              onChange={(e) => setFilter({ ...filter, severity: e.target.value || undefined, page: 1 })}>
              <option value="">모든 심각도</option><option>ERROR</option><option>WARN</option><option>INFO</option>
            </select>
            <Segmented ariaLabel="범위" value={filter.scope} onChange={(v) => setFilter({ ...filter, scope: v, run: undefined, page: 1 })}
              options={[{ value: "latest", label: "최신 run" }, { value: "all", label: "전체 기록" }]} />
            <button className="btn-ghost" onClick={() => setFilter({ scope: "latest", page: 1 })}>초기화</button>
          </div>}>
          {issuesView === "loading" ? <TableSkeleton rows={5} />
          : issuesView === "error" ? <div className="px-6 pb-6"><ErrorBox error={issuesQ.error?.message ?? ""} /></div>
          : issues && issuesView === "rows" ? (
            <div className="px-3 pb-3">
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead><tr><th>심각도</th><th>규칙</th><th>대상</th><th>내용</th><th>시각</th></tr></thead>
                  <tbody>
                    {issues.items.map((i) => (
                      <tr key={i.issueId}>
                        <td><span className={`badge ${SEV[i.severity]}`}>{i.severity}</span></td>
                        <td className="font-mono text-[12px]">{i.checkCode}</td>
                        <td className="text-[12px]"><span className="text-ink-3">{i.targetTable}</span><div className="font-mono">{i.targetKey}</div></td>
                        <td><Detail d={i.detail} /></td>
                        <td className="whitespace-nowrap text-[12px] text-ink-2">{dt(i.createdAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex items-center justify-end gap-2 text-[13px]">
                <span className="text-ink-3">{num(issues.total)}건</span>
                <button className="btn-ghost" disabled={filter.page <= 1} onClick={() => setFilter({ ...filter, page: filter.page - 1 })}>이전</button>
                <span className="tnum">{filter.page} / {Math.max(1, Math.ceil(issues.total / 30))}</span>
                <button className="btn-ghost" disabled={filter.page * 30 >= issues.total} onClick={() => setFilter({ ...filter, page: filter.page + 1 })}>다음</button>
              </div>
            </div>
          ) : <div className="px-6 pb-6"><Empty>조건에 맞는 이슈가 없습니다.</Empty></div>}
        </Card>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Card title="최근 수집" pad={false}>
            {runsQ.error ? <div className="px-6 pb-6"><ErrorBox error={runsQ.error.message} /></div>
            : !runsQ.data ? <TableSkeleton rows={5} /> : (
            <div className="overflow-x-auto px-3 pb-3">
              <table className="tbl">
                <thead><tr><th>종류</th><th>상태</th><th className="num">행</th><th className="num">호출</th><th>시작</th></tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.collectRunId} title={r.error || ""}>
                      <td><span className="font-medium">{KIND_LABEL[r.kind] || r.kind}</span><div className="font-mono text-[10px] text-ink-3">{short(r.collectRunId)}</div></td>
                      <td><span className={`badge ${STATUS[r.status] || "badge-info"}`}>{r.status}</span></td>
                      <td className="num">{num(r.stats.rows as number)}</td>
                      <td className="num">{num(r.stats.calls as number)}</td>
                      <td className="whitespace-nowrap text-[12px] text-ink-2">{dt(r.startedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}
          </Card>
          <Card title="최근 계산" pad={false}>
            {calcsQ.error ? <div className="px-6 pb-6"><ErrorBox error={calcsQ.error.message} /></div>
            : !calcsQ.data ? <TableSkeleton rows={5} /> : (
            <div className="overflow-x-auto px-3 pb-3">
              <table className="tbl">
                <thead><tr><th>calcRun</th><th>상태</th><th className="num">지역</th><th className="num">시설</th><th className="num">소요</th></tr></thead>
                <tbody>
                  {calcs.map((r) => (
                    <tr key={r.calcRunId} title={r.error || ""}>
                      <td className="font-mono text-[12px]">{short(r.calcRunId)}<div className="font-sans text-[10px] text-ink-3">{dt(r.createdAt)}</div></td>
                      <td><span className={`badge ${STATUS[r.status] || "badge-info"}`}>{r.status}</span></td>
                      <td className="num">{num(r.stats.areas)}</td>
                      <td className="num">{num(r.stats.facilities)}</td>
                      <td className="num">{r.stats.elapsedMs ? `${num(r.stats.elapsedMs / 1000, 1)}s` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}
          </Card>
        </div>
      </div>
    </Layout>
  );
}

function Detail({ d }: { d: Record<string, unknown> }) {
  const entries = Object.entries(d || {});
  if (!entries.length) return <span className="text-ink-3">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded-[6px] bg-surface px-1.5 py-0.5 text-[12px]">
          <span className="text-ink-3">{DETAIL_LABEL[k] || k}</span>{" "}
          <span className="font-medium">{typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(5)) : v === null ? "—" : String(v)}</span>
        </span>
      ))}
    </div>
  );
}
