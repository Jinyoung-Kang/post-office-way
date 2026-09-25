import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/Layout";
import { Skeleton } from "@/components/Skeleton";
import { api } from "@/lib/api";

type Entry = { at: string; source: string; ref: string; title: string; message: string; line: string };
const SOURCES = ["전체", "API", "작업", "수집", "계산", "품질", "화면"] as const;

// 오류 로그 — 흩어져 있던 실패(API 예외·작업·수집·계산·품질 ERROR·이 화면의 요청 실패)를 한곳에 시간순으로.
// 한 줄 로그 형식이라 그대로 복사해 이슈·메신저에 붙일 수 있음
export default function ErrorLog({ clientErrors = [] }: { clientErrors?: string[] }) {
  const [items, setItems] = useState<Entry[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [src, setSrc] = useState<(typeof SOURCES)[number]>("전체");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api<{ items: Entry[] }>("/meta/errors?days=14").then((r) => { if (alive) setItems(r.items); })
      .catch((e) => { if (alive) { setItems([]); setFailed(e.message); } });
    return () => { alive = false; };
  }, []);

  const all: Entry[] = useMemo(() => {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    const local = [...clientErrors, ...(failed ? [`오류 로그 조회 실패: ${failed}`] : [])]
      .map((m) => ({ at: now.toISOString(), source: "화면", ref: "-", title: location.pathname, message: m,
        line: `${stamp} [화면] ${location.pathname} — ${m}` }));
    return [...local, ...(items || [])];
  }, [items, clientErrors, failed]);
  const shown = src === "전체" ? all : all.filter((e) => e.source === src);
  const counts = useMemo(() => Object.fromEntries(SOURCES.map((s) => [s, s === "전체" ? all.length : all.filter((e) => e.source === s).length])), [all]);

  async function copy(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {                                         // http(localhost) 가 아닌 곳에서 clipboard API 가 막히면 대체
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    setCopied(key);
    setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
  }

  return (
    <Card title={<span className="flex items-center gap-2">오류 로그
      {items && <span className={`badge ${all.length ? "badge-error" : "badge-good"}`}>{all.length ? `${all.length}건` : "없음"}</span>}</span>}
      pad={false}
      right={all.length > 0 && (
        <button className="btn-ghost text-[13px]" onClick={() => copy(shown.map((e) => e.line).join("\n"), "all")}>
          {copied === "all" ? "복사했습니다 ✓" : `${src === "전체" ? "모두" : src} 복사 (${shown.length})`}
        </button>
      )}>
      <p className="-mt-2 px-6 pb-3 text-[13px] text-ink-2">최근 14일 · API 예외, 작업·수집·계산 실패, 품질 ERROR 규칙, 이 화면의 요청 실패를 시간순으로 모았습니다. 키 값은 가려져 있습니다.</p>
      {!items ? <div className="px-6 pb-6"><Skeleton className="h-24 w-full" /></div> : all.length === 0 ? (
        <p className="px-6 pb-6 text-[14px] text-[#1d8a3a]">최근 14일 동안 기록된 오류가 없습니다.</p>
      ) : (
        <div className="px-3 pb-3">
          <div className="mb-2 flex flex-wrap gap-1.5 px-3" role="radiogroup" aria-label="출처">
            {SOURCES.filter((s) => s === "전체" || counts[s]).map((s) => (
              <button key={s} role="radio" aria-checked={src === s} onClick={() => setSrc(s)}
                className={`badge ${src === s ? "badge-error" : "badge-info"}`}>{s} {counts[s]}</button>
            ))}
          </div>
          <ol className="max-h-[360px] overflow-auto rounded-[12px] bg-[#1d1d1f] p-2 font-mono text-[12px] leading-relaxed text-[#f5f5f7]">
            {shown.map((e, i) => (
              <li key={`${e.line}-${i}`} className="group/log flex items-start gap-2 rounded-[6px] px-2 py-1 hover:bg-white/10">
                <span className="min-w-0 flex-1 whitespace-pre-wrap break-all select-text">{e.line}</span>
                <button onClick={() => copy(e.line, `l${i}`)} aria-label="이 줄 복사"
                  className="shrink-0 rounded-[6px] px-1.5 text-[11px] text-white/60 opacity-0 hover:text-white focus:opacity-100 group-hover/log:opacity-100">
                  {copied === `l${i}` ? "✓" : "복사"}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}
