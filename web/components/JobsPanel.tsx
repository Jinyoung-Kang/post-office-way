import { useEffect, useState } from "react";
import { Card } from "@/components/Layout";
import { TableSkeleton } from "@/components/Skeleton";
import { api, type Job, type ScheduleItem } from "@/lib/api";
import { dt, num } from "@/lib/format";

type Health = { status: string; schema: { upToDate: boolean; pending: string[] } | null;
  queue: { queued: number; running: number; oldestQueuedS: number | null } | null; redis: boolean };

const STATUS: Record<Job["status"], string> = { DONE: "badge-good", FAILED: "badge-error", RUNNING: "badge-info",
  QUEUED: "badge-info", CANCELLED: "badge-info" };
const SOURCE: Record<string, string> = { api: "관리 API", schedule: "스케줄", chain: "자동 재계산", cli: "CLI" };
const WD = "월화수목금토일";

// 작업 큐·스케줄 — 워커가 무엇을 언제 실행했는지. 실행 중인 작업이 있으면 10초마다 새로 고침
export default function JobsPanel() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [sched, setSched] = useState<{ groups: string; items: ScheduleItem[]; titles: Record<string, string> } | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = async () => {
      const [j, s, h] = await Promise.all([
        api<{ items: Job[] }>("/meta/jobs?limit=15").catch(() => null),
        api<{ groups: string; items: ScheduleItem[]; titles: Record<string, string> }>("/meta/schedule").catch(() => null),
        fetch("/api/v1/health").then((r) => r.json() as Promise<Health>).catch(() => null),
      ]);
      if (!alive) return;
      if (j) setJobs(j.items);
      if (s) setSched(s);
      if (h) setHealth(h);
      const busy = j?.items.some((x) => x.status === "QUEUED" || x.status === "RUNNING");
      if (busy && document.visibilityState === "visible") timer = setTimeout(load, 10_000);
    };
    load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);

  const stale = (health?.queue?.oldestQueuedS ?? 0) > 600;
  return (
    <Card title="작업 큐 · 스케줄" pad={false}
      right={health && (
        <span className="flex flex-wrap items-center gap-2 text-[12px]">
          <span className={`badge ${health.schema?.upToDate ? "badge-good" : "badge-error"}`}>
            스키마 {health.schema?.upToDate ? "최신" : `대기 ${health.schema?.pending.length}`}</span>
          <span className={`badge ${stale ? "badge-error" : "badge-info"}`} title={stale ? "10분 넘게 대기 — 워커(compose 서비스 worker)를 확인하세요" : undefined}>
            대기 {num(health.queue?.queued)} · 실행 {num(health.queue?.running)}</span>
          <span className={`badge ${health.redis ? "badge-good" : "badge-warn"}`}>캐시 {health.redis ? "연결" : "없음"}</span>
        </span>
      )}>
      <p className="-mt-2 px-6 pb-3 text-[13px] text-ink-2">
        관리 API·스케줄이 넣은 작업을 워커가 차례로 실행합니다(Postgres 작업 큐). 수집이 끝나면 지표 재계산이 자동으로 이어집니다.
      </p>
      <div className="grid gap-5 px-3 pb-3 lg:grid-cols-[1fr_320px]">
        <div className="overflow-x-auto">
          {!jobs ? <TableSkeleton rows={5} /> : jobs.length ? (
            <table className="tbl">
              <thead className="whitespace-nowrap"><tr><th>작업</th><th>상태</th><th>요청</th><th>시작</th><th className="num">소요</th></tr></thead>
              <tbody>{jobs.map((j) => {
                const secs = j.startedAt && j.finishedAt ? (new Date(j.finishedAt).getTime() - new Date(j.startedAt).getTime()) / 1000 : null;
                return (
                  <tr key={j.jobId} title={j.error || ""}>
                    <td className="whitespace-nowrap"><span className="font-medium">{sched?.titles[j.kind] || j.kind}</span>
                      <div className="font-mono text-[10px] text-ink-3">#{j.jobId}{j.attempts > 1 ? ` · 시도 ${j.attempts}` : ""}</div></td>
                    <td><span className={`badge ${STATUS[j.status]}`}>{j.status}</span></td>
                    <td className="whitespace-nowrap text-[12px] text-ink-2">{SOURCE[j.source] || j.source}</td>
                    <td className="whitespace-nowrap text-[12px] text-ink-2">{dt(j.startedAt || j.createdAt)}</td>
                    <td className="num text-[12px]">{secs === null ? "—" : secs >= 60 ? `${num(secs / 60, 1)}분` : `${num(secs, 0)}초`}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          ) : <p className="px-3 py-4 text-[14px] text-ink-2">아직 실행한 작업이 없습니다. <code>make enqueue KIND=calc</code> 또는 관리 API 로 요청하세요.</p>}
        </div>
        <div>
          <p className="group-label">자동 실행 (ATLAS_SCHEDULE={sched?.groups || "—"})</p>
          <div className="group">
            {(sched?.items || []).map((s) => (
              <div key={s.kind} className="row items-start">
                <span className="min-w-0">
                  <span className="block font-medium">{s.title}</span>
                  <span className="block text-[12px] text-ink-3">
                    {s.weekdays ? `매주 ${s.weekdays.map((d) => WD[d]).join("·")} ` : "매일 "}{s.times.length > 3 ? `${s.times.length}회` : s.times.join(", ")} · {s.note}</span>
                </span>
                <span className="shrink-0 text-right text-[12px]">
                  {s.missingKeys.length ? <span className="badge badge-warn" title={s.missingKeys.join(", ")}>키 없음</span>
                    : s.enabled ? <span className="text-ink-2">다음 {s.nextRunAt ? s.nextRunAt.slice(5, 16).replace("T", " ") : "—"}</span>
                    : <span className="text-ink-3">꺼짐</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
