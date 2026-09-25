import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState, type ReactNode } from "react";
import { api, type CalendarDay } from "@/lib/api";
import { dt, short } from "@/lib/format";

const NAV = [
  { href: "/overview", label: "한눈에" },
  { href: "/", label: "지도" },
  { href: "/today", label: "방문 여건" },
  { href: "/hubs", label: "생활 거점" },
  { href: "/rankings", label: "지역 순위" },
  { href: "/whatif", label: "What-if" },
  { href: "/plan", label: "배치 제안" },
  { href: "/quality", label: "데이터·운영" },
  { href: "/about/metrics", label: "지표 정의" },
];

type CalcRun = { calcRunId: string; statYear: number; facilityAsOf: string; status: string;
  stats: { kosisRefPeriod?: string | null } };

export function useDataBasis() {
  const [calc, setCalc] = useState<CalcRun | null>(null);
  const [dqErrors, setDqErrors] = useState(0);
  useEffect(() => {
    api<{ items: CalcRun[] }>("/meta/calc-runs?size=10").then((r) => setCalc(r.items.find((x) => x.status === "DONE") || null)).catch(() => null);
    api<{ errorCount: number }>("/dq/summary").then((r) => setDqErrors(r.errorCount)).catch(() => null);
  }, []);
  return { calc, dqErrors };
}

export function basisText(calc: CalcRun | null): string {
  if (!calc) return "계산된 데이터 없음";
  const k = calc.stats?.kosisRefPeriod;
  return `시설 ${dt(calc.facilityAsOf)} 수집 · 인구 ${calc.statYear}년 SGIS${k ? ` · 주민등록 ${k.slice(0, 4)}.${k.slice(4)} KOSIS` : ""} · calcRun ${short(calc.calcRunId)}`;
}

// 오늘이 창구 휴무일(주말·공휴일)이면 머리글에 알림 — 특일 정보가 있을 때만 공휴일 이름까지
function useToday() {
  const [day, setDay] = useState<CalendarDay | null>(null);
  useEffect(() => {
    api<{ items: CalendarDay[] }>("/calendar?days=1").then((r) => setDay(r.items[0] || null)).catch(() => null);
  }, []);
  return day;
}

export default function Layout({ children, full, title }: { children: ReactNode; full?: boolean; title?: string }) {
  const { pathname } = useRouter();
  const { calc, dqErrors } = useDataBasis();
  const today = useToday();

  return (
    <div className={`flex flex-col ${full ? "h-[100dvh]" : "min-h-screen"}`}>
      <Head><title>{title ? `${title} — 우체국 가는 길` : "우체국 가는 길"}</title></Head>
      <a href="#main" className="skip-link">본문으로 건너뛰기</a>
      <header className="gnav">
        <div className="mx-auto flex h-full max-w-wide items-center gap-2 px-4">
          <Link href="/overview" className="mr-2 flex shrink-0 items-center gap-2 text-ink no-underline" aria-label="우체국 가는 길 홈">
            <Logo />
            <span className="hidden text-[14px] font-semibold tracking-tight sm:inline">우체국 가는 길</span>
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
      <main id="main" className={`flex-1 ${full ? "relative min-h-0" : ""}`}>{children}</main>
      {!full && (
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto max-w-page space-y-2 px-4 py-6 text-[12px] leading-relaxed text-ink-2">
            <p>이 서비스의 지표는 분석용으로 정의한 값이며 공식 통계가 아닙니다. 거리는 직선거리(EPSG:5179)입니다.</p>
            <p>데이터 기준 — {basisText(calc)}</p>
            <p className="text-ink-3">출처: 우정사업본부 「우체국 찾기」 · 통계청 SGIS(총조사 주요지표·행정구역·집계구 경계) · KOSIS 주민등록인구(행정안전부) · 카카오(지도·로컬·모빌리티) · 기상청 단기예보 · 한국환경공단 에어코리아 · 국립중앙의료원 약국·병의원 · 한국천문연구원 특일 정보</p>
          </div>
        </footer>
      )}
    </div>
  );
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="6" fill="#1d1d1f" />
      <path d="M12 6.2a4.3 4.3 0 0 0-4.3 4.3c0 3.2 4.3 7.3 4.3 7.3s4.3-4.1 4.3-7.3A4.3 4.3 0 0 0 12 6.2Z" fill="#fff" />
      <circle cx="12" cy="10.5" r="1.6" fill="#1d1d1f" />
    </svg>
  );
}

export function Hero({ eyebrow, title, sub, children }: { eyebrow?: string; title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <section className="rise mx-auto max-w-page px-4 pb-8 pt-14 text-center md:pt-20">
      {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
      <h1 className="hero-title">{title}</h1>
      {sub && <p className="hero-sub mx-auto mt-4 max-w-2xl">{sub}</p>}
      {children && <div className="mt-6 flex flex-wrap items-center justify-center gap-3">{children}</div>}
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
    <div className="card p-5">
      <div className="text-[13px] font-medium text-ink-2">{label}</div>
      <div className={`tnum mt-1 text-[28px] font-semibold leading-tight tracking-tight ${tone === "bad" ? "text-[#d70015]" : ""}`}>{value}</div>
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
