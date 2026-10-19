import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { type ReactNode } from "react";
import { useApi } from "@/hooks/useApi";
import { type CalendarDay } from "@/lib/api";
import { dt, sentences, short } from "@/lib/format";
import Sents from "@/components/Sents";

const NAV = [
  { href: "/overview", label: "한눈에" },
  { href: "/", label: "지도" },
  { href: "/today", label: "방문 여건" },
  { href: "/hubs", label: "생활 거점" },
  { href: "/banks", label: "은행 지점" },
  { href: "/rankings", label: "지역 순위" },
  { href: "/whatif", label: "What-if" },
  { href: "/plan", label: "배치 제안" },
  { href: "/quality", label: "데이터·운영" },
  { href: "/about/metrics", label: "지표 정의" },
];

type CalcRun = { calcRunId: string; statYear: number; facilityAsOf: string; status: string;
  stats: { kosisRefPeriod?: string | null; migrationWindow?: { from: string; to: string } | null } };

export function useDataBasis() {
  const runs = useApi<{ items: CalcRun[] }>("/meta/calc-runs?size=10", { cacheMs: 60_000 }).data;
  const calc = runs?.items.find((x) => x.status === "DONE") || null;
  const dqErrors = useApi<{ errorCount: number }>("/dq/summary", { cacheMs: 60_000 }).data?.errorCount ?? 0;
  return { calc, dqErrors };
}

export function basisText(calc: CalcRun | null): string {
  if (!calc) return "계산된 데이터 없음";
  const k = calc.stats?.kosisRefPeriod;
  const w = calc.stats?.migrationWindow;   // 인구 추세 지표의 12개월 (ADR-028)
  const ym = (p: string) => `${p.slice(0, 4)}.${p.slice(4)}`;
  return `시설 ${dt(calc.facilityAsOf)} 수집 · 인구 ${calc.statYear}년 SGIS${k ? ` · 주민등록 ${ym(k)} KOSIS` : ""}`
    + `${w ? ` · 인구이동 ${ym(w.from)}~${ym(w.to)} 행안부` : ""} · calcRun ${short(calc.calcRunId)}`;
}

// 오늘이 창구 휴무일(주말·공휴일)이면 머리글에 알림 — 특일 정보가 있을 때만 공휴일 이름까지
function useToday() {
  return useApi<{ items: CalendarDay[] }>("/calendar?days=1", { cacheMs: 600_000 }).data?.items[0] || null;
}

export default function Layout({ children, full, title }: { children: ReactNode; full?: boolean; title?: string }) {
  const { pathname } = useRouter();
  const { calc, dqErrors } = useDataBasis();
  const today = useToday();

  return (
    <div className={`flex flex-col ${full ? "h-dvh" : "min-h-screen"}`}>
      <Head><title>{title ? `${title} — 우체국 가는 길` : "우체국 가는 길"}</title></Head>
      <a href="#main" className="skip-link">본문으로 건너뛰기</a>
      <header className="gnav">
        <div className="mx-auto flex h-full max-w-wide items-center gap-2 px-4">
          <Link href="/overview" className="mr-2 shrink-0 text-[14px] font-semibold tracking-tight text-ink no-underline" aria-label="우체국 가는 길 홈">
            우체국 가는 길
          </Link>
          <nav className="-mx-1 flex flex-1 items-center justify-start gap-0.5 overflow-x-auto md:justify-center">
            {NAV.map((n) => {
              const on = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <Link key={n.href} href={n.href} className={`item ${on ? "on" : ""}`} aria-current={on ? "page" : undefined}>
                  {n.label}
                  {n.href === "/quality" && dqErrors > 0 && (
                    <span className="ml-1 inline-block h-1.5 w-1.5 -translate-y-0.5 rounded-full bg-[#d70015]" title={`ERROR 품질 이슈 ${dqErrors}건`} />
                  )}
                </Link>
              );
            })}
          </nav>
          <span className="hidden w-[150px] shrink-0 justify-end md:flex">
            {today?.closed && (
              <Link href="/today" className="badge badge-warn no-underline" title="우체국 창구 휴무 — 365코너·휴일 진료처 기준은 방문 여건에서">
                오늘 휴무 · {today.holiday || today.reason}
              </Link>
            )}
          </span>
        </div>
      </header>
      <main id="main" className={`flex-1 ${full ? "relative min-h-0" : "min-h-[calc(100dvh-48px)]"}`}>{children}</main>
      {!full && (
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto max-w-page space-y-2 px-4 py-6 text-[12px] leading-relaxed text-ink-2">
            <p><Sents>이 서비스의 지표는 분석용으로 정의한 값이며 공식 통계가 아닙니다. 거리는 직선거리(EPSG:5179)이고, ‘걸어서’ 지표는
              OpenStreetMap 보행 도로망 최단 경로(고령자 0.8m/s)입니다.</Sents></p>
            <p>데이터 기준 — {basisText(calc)}</p>
            <p className="text-ink-3">출처: 우정사업본부 「우체국 찾기」 · 통계청 SGIS(총조사 주요지표·행정구역·집계구 경계) · KOSIS 주민등록인구(행정안전부) · 카카오(지도·로컬·모빌리티) · 기상청 단기예보 · 한국환경공단 에어코리아 · 국립중앙의료원 약국·병의원 · 한국천문연구원 특일 정보 · 행정안전부 지역별 인구이동 · 도보 도로망 © OpenStreetMap 기여자(ODbL)</p>
          </div>
        </footer>
      )}
    </div>
  );
}

// 화면 머리 — 메뉴 이름(h1)과 설명. 왼쪽 정렬, 본문 틀과 같은 폭(wide = 넓은 화면)이라 왼쪽 끝이 아래 카드와 맞음.
// 설명은 문장마다 줄을 바꿔 구절 중간에서 끊기지 않게 (좁은 화면에서는 어절 단위로만 줄바꿈)
export function Hero({ title, sub, children, wide }: { title: string; sub?: string; children?: ReactNode; wide?: boolean }) {
  return (
    <section className={`rise mx-auto px-4 pb-6 pt-8 md:pt-10 ${wide ? "max-w-wide" : "max-w-page"}`}>
      <h1 className="page-name">{title}</h1>
      {sub && (
        <p className="page-desc mt-2">
          {sentences(sub).map((s) => <span key={s} className="block">{s}</span>)}
        </p>
      )}
      {children && <div className="mt-5 flex flex-wrap items-center gap-3">{children}</div>}
    </section>
  );
}

export function Card({ title, children, className, right, pad = true }: {
  title?: ReactNode; children: ReactNode; className?: string; right?: ReactNode; pad?: boolean;
}) {
  return (
    <section className={`card ${pad ? "p-6" : ""} ${className || ""}`}>
      {(title || right) && (
        <div className={`mb-4 flex flex-wrap items-center justify-between gap-2 ${pad ? "" : "px-6 pt-6"}`}>
          {title && <h2 className="text-[19px] font-semibold tracking-tight">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, note, tone }: { label: string; value: ReactNode; note?: ReactNode; tone?: "bad" | "good" }) {
  return (
    <div className="card @container p-5">
      <div className="text-[13px] font-medium text-ink-2">{label}</div>
      {/* 글자 크기를 카드 폭에 맞춤(최대 28px) — 375px 두 칸·768px 네 칸에서도 '2,517,187명'이 한 줄에 들어가게 */}
      <div className={`tnum mt-1 text-[clamp(18px,15cqi,28px)] font-semibold leading-tight tracking-tight ${tone === "bad" ? "text-[#d70015]" : ""}`}>{value}</div>
      {note && <div className="mt-1 text-[12px] text-ink-3">{note}</div>}
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, ariaLabel }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; ariaLabel?: string;
}) {
  return (
    <div className="seg" role="radiogroup" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" role="radio" aria-checked={value === o.value}
          className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-[18px] border border-dashed border-black/10 p-8 text-center text-[14px] text-ink-2">{children}</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="rounded-[14px] bg-[#d70015]/[.07] px-4 py-3 text-[14px] text-[#b00012]">{error}</div>;
}

export function NoDataGuide() {
  return (
    <div className="card mx-auto max-w-md p-6 text-center">
      <p className="text-[17px] font-semibold">아직 계산된 데이터가 없습니다</p>
      <p className="mt-1 text-[14px] text-ink-2">터미널에서 수집과 계산을 한 번 실행하세요.</p>
      <pre className="mt-3 rounded-[10px] bg-surface p-3 text-[13px]">make all-data</pre>
    </div>
  );
}
