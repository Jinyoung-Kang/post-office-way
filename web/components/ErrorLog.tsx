import { useCallback, useEffect, useMemo, useState } from "react";
import { Card } from "@/components/Layout";
import { Skeleton } from "@/components/Skeleton";
import { api, ApiError } from "@/lib/api";

type Entry = { id?: string; at: string; source: string; ref: string; title: string; message: string; line: string };
const SOURCES = ["전체", "API", "보안 정책", "작업", "수집", "계산", "품질", "화면"] as const;

// 오류 로그 — 흩어져 있던 실패(API 예외·작업·수집·계산·품질 ERROR·이 화면의 요청 실패)를 한곳에 시간순으로.
// 한 줄 로그 형식이라 그대로 복사해 이슈·메신저에 붙일 수 있음.
// 지우기는 확인 표시(ops.error_ack)라 원본 이력은 남고, 관리 토큰이 필요함 — 토큰은 이 화면의 메모리에만 둠(저장하지 않음)
export default function ErrorLog({ clientErrors = [] }: { clientErrors?: string[] }) {
  const [items, setItems] = useState<Entry[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [src, setSrc] = useState<(typeof SOURCES)[number]>("전체");
  const [copied, setCopied] = useState<string | null>(null);
  const [hiddenLocal, setHiddenLocal] = useState<Set<string>>(new Set());   // '화면' 항목은 서버에 없어 이 화면에서만 숨김
  const [token, setToken] = useState("");
  const [pending, setPending] = useState<Entry[] | null>(null);             // 지우기 확인 중인 항목
  const [draft, setDraft] = useState("");
  const [ackMsg, setAckMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (signal?: { alive: boolean }) => {
    setLoading(true);
    try {
      const r = await api<{ items: Entry[] }>("/meta/errors?days=14");
      if (signal?.alive !== false) { setItems(r.items); setFailed(null); }
    } catch (e) {
      if (signal?.alive !== false) { setItems((v) => v || []); setFailed((e as Error).message); }
    } finally {
      if (signal?.alive !== false) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const signal = { alive: true };
    load(signal);
    return () => { signal.alive = false; };
  }, [load]);

  const all: Entry[] = useMemo(() => {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    const local = [...clientErrors, ...(failed ? [`오류 로그 조회 실패: ${failed}`] : [])]
      .filter((m) => !hiddenLocal.has(m))
      .map((m) => ({ at: now.toISOString(), source: "화면", ref: "-", title: location.pathname, message: m,
        line: `${stamp} [화면] ${location.pathname} — ${m}` }));
    return [...local, ...(items || [])];
  }, [items, clientErrors, failed, hiddenLocal]);
  const shown = src === "전체" ? all : all.filter((e) => e.source === src);
  const counts = useMemo(() => Object.fromEntries(SOURCES.map((s) => [s, s === "전체" ? all.length : all.filter((e) => e.source === s).length])), [all]);
  const label = src === "전체" ? "모두" : src;

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

  // 지우기 — 서버 항목은 확인 표시, '화면' 항목은 이 화면에서만 숨김. 토큰이 없거나 여러 건이면 먼저 확인
  function ask(targets: Entry[]) {
    setAckMsg(null);
    if (targets.length === 1 && token) { void remove(targets, token); return; }
    setPending(targets);
  }

  async function remove(targets: Entry[], tk: string) {
    const ids = targets.map((e) => e.id).filter((x): x is string => !!x);
    setBusy(true);
    try {
      if (ids.length) {
        await api<{ acked: number }>("/admin/errors/ack", {
          method: "POST", headers: { "X-Admin-Token": tk }, body: JSON.stringify({ ids }),
        });
        setToken(tk);
        const gone = new Set(ids);
        setItems((v) => (v || []).filter((e) => !e.id || !gone.has(e.id)));
      }
      const locals = targets.filter((e) => !e.id);
      if (locals.length) {
        setHiddenLocal((h) => new Set([...h, ...locals.map((e) => e.message)]));
        if (locals.some((e) => e.message.startsWith("오류 로그 조회 실패"))) setFailed(null);   // 새로 고침 실패 줄
      }
      setPending(null); setDraft("");
      setAckMsg(`${targets.length}건을 지웠습니다`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setToken(""); setDraft(""); setPending(targets); setAckMsg("관리 토큰이 맞지 않습니다."); }
      else setAckMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const needToken = !!pending?.some((e) => e.id) && !token;

  return (
    <Card title={<span className="flex items-center gap-2">오류 로그
      {items && <span className={`badge ${all.length ? "badge-error" : "badge-good"}`}>{all.length ? `${all.length}건` : "없음"}</span>}</span>}
      pad={false}
      right={
        // 불러오기 전후로 머리글 높이가 같도록 버튼은 늘 두고 비활성만 바꿈 (CLS)
        <div className="flex flex-wrap items-center gap-1">
          <button className="btn-ghost text-[13px]" disabled={loading} aria-busy={loading} onClick={() => { setAckMsg(null); void load(); }}>
            <span aria-hidden className={loading ? "inline-block animate-spin" : "inline-block"}>↻</span> 새로 고침
          </button>
          <button className="btn-ghost text-[13px]" disabled={!shown.length || busy} onClick={() => ask(shown)}>
            {label} 지우기
          </button>
          <button className="btn-ghost text-[13px]" disabled={!shown.length}
            onClick={() => copy(shown.map((e) => e.line).join("\n"), "all")}>
            {copied === "all" ? "복사했습니다 ✓" : `${label} 복사 (${shown.length})`}
          </button>
        </div>
      }>
      <p className="-mt-2 px-6 pb-3 text-[13px] text-ink-2">최근 14일 · API 예외, 작업·수집·계산 실패, 품질 ERROR 규칙, 이 화면의 요청 실패를 시간순으로 모았습니다. 키 값은 가려져 있습니다. 지운 항목은 이 로그에서만 빠지고 작업·품질 이력에는 남습니다.</p>

      {pending && (
        <form className="mx-6 mb-3 flex flex-wrap items-end gap-2 rounded-[12px] bg-surface p-3"
          onSubmit={(e) => { e.preventDefault(); void remove(pending, token || draft.trim()); }}>
          <p className="w-full text-[13px]">
            <b>{pending.length}건</b>을 오류 로그에서 지울까요? 원본 기록은 남습니다.
          </p>
          {needToken && (
            <label className="min-w-0 flex-1 text-[12px] text-ink-2">
              관리 토큰 (.env 의 ADMIN_TOKEN · 이 화면에서만 기억)
              <input type="password" autoComplete="off" spellCheck={false} required value={draft}
                onChange={(e) => setDraft(e.target.value)} className="field mt-1" autoFocus />
            </label>
          )}
          <button type="submit" className="btn text-[13px]" disabled={busy || (needToken && !draft.trim())}>지우기</button>
          <button type="button" className="btn-ghost text-[13px]" onClick={() => { setPending(null); setDraft(""); setAckMsg(null); }}>취소</button>
        </form>
      )}
      <p className="sr-only" aria-live="polite">{ackMsg || ""}</p>
      {ackMsg && <p className="-mt-1 px-6 pb-2 text-[12px] text-ink-2">{ackMsg}</p>}

      {/* 로그 창은 불러오는 중·오류 없음·오류 있음 모두 같은 높이 — 아래 작업 큐 카드가 밀리지 않게 */}
      <div className="px-3 pb-3">
        <div className="mb-2 flex h-7 items-center gap-1.5 overflow-x-auto px-3" role="radiogroup" aria-label="출처">
          {!items ? <Skeleton className="h-5 w-48" /> : SOURCES.filter((s) => s === "전체" || counts[s]).map((s) => (
            <button key={s} role="radio" aria-checked={src === s} onClick={() => setSrc(s)}
              className={`badge shrink-0 ${src === s ? "badge-error" : "badge-info"}`}>{s} {counts[s] || 0}</button>
          ))}
        </div>
        {!items ? <Skeleton className="h-[240px] w-full rounded-[12px]!" /> : (
          <ol className="h-[240px] overflow-auto rounded-[12px] bg-ink p-2 font-mono text-[12px] leading-relaxed text-surface">
            {all.length === 0 && <li className="px-2 py-1 text-[#7ee29a]">최근 14일 동안 기록된 오류가 없습니다.</li>}
            {shown.map((e, i) => (
              <li key={`${e.id || e.line}-${i}`} className="group/log flex items-start gap-2 rounded-[6px] px-2 py-1 hover:bg-white/10">
                <span className="min-w-0 flex-1 whitespace-pre-wrap break-all select-text">{e.line}</span>
                <span className="flex shrink-0 gap-0.5 opacity-0 group-hover/log:opacity-100 focus-within:opacity-100">
                  <button onClick={() => copy(e.line, `l${i}`)} aria-label="이 줄 복사"
                    className="rounded-[6px] px-1.5 text-[11px] text-white/60 hover:text-white">
                    {copied === `l${i}` ? "✓" : "복사"}
                  </button>
                  <button onClick={() => ask([e])} aria-label="이 줄 지우기" disabled={busy}
                    className="rounded-[6px] px-1.5 text-[11px] text-white/60 hover:text-[#ff8a80]">지우기</button>
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}
