import Link from "next/link";
import { useEffect, useState } from "react";
import { api, qs, type AreaDetail, type Facility } from "@/lib/api";
import { dist, dt, num, short, withUnit } from "@/lib/format";
import { ErrorBox } from "@/components/Layout";

// 지역 카드 — 모든 숫자에 calc_run·수집 시점 표시 (FR-502, NFR-07)
export default function RegionCard({ admCd, calcRunId, highlight, onDrill, onClose }: {
  admCd: string; calcRunId?: string; highlight?: string; onDrill?: (admCd: string) => void; onClose?: () => void;
}) {
  const [d, setD] = useState<AreaDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setD(null); setErr(null);
    api<AreaDetail>(`/areas/${admCd}${qs({ calcRunId })}`).then(setD).catch((e) => setErr(e.message));
  }, [admCd, calcRunId]);

  if (err) return <ErrorBox error={err} />;
  if (!d) return <p className="p-2 text-[14px] text-ink-3">불러오는 중…</p>;
  const hl = d.metrics.find((m) => m.code === highlight);

  return (
    <div className="space-y-5 text-[14px]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[12px] font-medium text-ink-3">{d.parentNm || ""} · {d.level === 2 ? "시군구" : "읍면동"}</p>
          <h2 className="text-[26px] font-bold leading-tight tracking-tight">{d.admNm}</h2>
        </div>
        {onClose && <CloseButton onClick={onClose} />}
      </div>

      {hl && (
        <div>
          <p className="text-[12px] font-medium text-ink-2">{hl.name}</p>
          <p className="tnum text-[34px] font-semibold leading-none tracking-tight">{withUnit(hl.value, hl.unit)}</p>
          {hl.rank && <p className="mt-1 text-[12px] text-ink-3">전국 {hl.rankOf}곳 중 값이 큰 순 {hl.rank}위 · 백분위 {hl.percentile}</p>}
        </div>
      )}
      {onDrill && <button className="btn-ghost" onClick={() => onDrill(d.admCd)}>읍면동으로 보기</button>}

      <Group label="최근접 금융 가능 우체국 ⚠ 직선거리">
        {d.nearest.length ? d.nearest.map((n) => (
          <div key={n.rank} className="row">
            <span className="min-w-0">
              <span className="block truncate font-medium">{n.name}</span>
              <span className="block truncate text-[12px] text-ink-3">{n.addr || "—"} · 금융 {n.financeTime || "—"}</span>
            </span>
            <span className="tnum shrink-0 text-right">
              <span className="block font-medium">{dist(n.distM)}</span>
              {n.roadM !== null && <span className="block text-[11px] text-ink-3">도로 {dist(n.roadM)} · {num(n.driveMin, 0)}분</span>}
            </span>
          </div>
        )) : <div className="row text-ink-3">—</div>}
      </Group>

      <Group label="가까운 은행·금고 지점 (대면 창구) ⚠ 직선거리">
        {d.nearestBanks.length ? d.nearestBanks.map((b) => (
          <div key={`${b.name}${b.distM}`} className="row">
            <span className="min-w-0"><span className="block truncate font-medium">{b.name}</span>
              <span className="block truncate text-[12px] text-ink-3">{b.addr || "—"}</span></span>
            <span className="tnum shrink-0 font-medium">{dist(b.distM)}</span>
          </div>
        )) : <div className="row text-ink-3">자료 없음 (make banks 로 적재)</div>}
      </Group>

      <Group label="접근성 지표 (전국 순위)">
        {d.metrics.map((m) => (
          <div key={m.code} className="row" style={m.code === highlight ? { background: "rgba(0,113,227,.06)" } : undefined}>
            <span className="text-ink-2">{m.name}</span>
            <span className="tnum shrink-0 text-right">
              <span className="font-medium">{withUnit(m.value, m.unit)}</span>
              {m.rank && <span className="ml-2 text-[11px] text-ink-3">{m.rank}/{m.rankOf}</span>}
            </span>
          </div>
        ))}
      </Group>

      <Group label={`인구 · SGIS ${d.statYear}년 총조사`}>
        <Row k="총인구" v={`${num(d.population.totPpltn)}명`} />
        <Row k="노령화지수" v={num(d.population.agedChildIdx, 1)} />
        <Row k="평균연령" v={`${num(d.population.avgAge, 1)}세`} />
        <Row k="인구밀도" v={`${num(d.population.ppltnDnsty, 1)}명/㎢`} />
        <Row k="면적" v={`${num(d.areaKm2, 1)}㎢`} />
      </Group>

      <Group label={d.residentPop ? `주민등록인구 · KOSIS ${fmtPeriod(d.residentPop.refPeriod)}` : "주민등록인구 · KOSIS"}>
        {d.residentPop ? (
          <>
            <Row k="총 주민등록인구" v={`${num(d.residentPop.totPpltn)}명`} />
            <Row k="65세 이상" v={`${num(d.residentPop.aged65Ppltn)}명`} />
            <Row k="고령인구 비율" v={`${num(d.residentPop.aged65Ratio, 1)}%`} />
          </>
        ) : <div className="row text-ink-3">KOSIS 자료 없음 (make kosis 로 적재)</div>}
      </Group>

      <Group label="지역 안 시설 (좌표 공간 조인)">
        {d.facilities.length ? d.facilities.map((f) => <Row key={f.postDiv} k={f.divLabel} v={`${f.count}곳`} />)
          : <div className="row text-ink-3">—</div>}
      </Group>

      <p className="text-[11px] leading-relaxed text-ink-3">
        calcRun {short(d.meta.calcRunId)} · 시설 기준 {dt(d.meta.facilityAsOf)} · 인구 적재 {dt(d.population.loadedAt)}
        {d.residentPop?.matchMethod && d.residentPop.matchMethod !== "NAME" && ` · KOSIS 매칭 ${d.residentPop.matchMethod}`}
      </p>
    </div>
  );
}

export function FacilityCard({ f: base, onClose }: { f: Facility; onClose?: () => void }) {
  // 지도 레이어 항목에는 좌표 검증 결과가 없어 상세를 한 번 더 조회
  const [detail, setDetail] = useState<Facility | null>(null);
  useEffect(() => { setDetail(null); api<Facility>(`/facilities/${base.histId}`).then(setDetail).catch(() => null); }, [base.histId]);
  const f = detail || base;
  return (
    <div className="space-y-5 text-[14px]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[12px] font-medium text-ink-3">{f.divLabel}</p>
          <h2 className="text-[24px] font-bold leading-tight tracking-tight">{f.name}</h2>
          {f.addr && <p className="mt-0.5 text-[13px] text-ink-2">{f.addr}</p>}
        </div>
        {onClose && <CloseButton onClick={onClose} />}
      </div>
      <div className="flex flex-wrap gap-1.5">
        <span className={`badge ${f.finAvailable ? "badge-good" : "badge-info"}`}>{f.finAvailable ? "금융 가능" : "금융 불가"}</span>
        {f.post365Yn === "Y" && <span className="badge badge-info">365코너</span>}
        {f.lunchYn === "Y" && <span className="badge badge-warn">점심 휴무</span>}
        {f.coordSource === "GEOCODE" && <span className="badge badge-info">좌표: 주소로 보완</span>}
        {f.geocheck?.status === "MISMATCH" && <span className="badge badge-warn">주소와 {dist(f.geocheck.distM)} 차이</span>}
        {f.geocheck?.status === "OK" && <span className="badge badge-good">주소 좌표 일치</span>}
      </div>
      <Group label="운영">
        <Row k="우편 업무" v={f.postTime || "—"} />
        <Row k="금융 업무" v={f.financeTime || "—"} />
        <Row k="점심시간" v={f.lunchYn === "Y" ? f.lunchTime || "있음" : "없음"} />
      </Group>
      <Group label="연락처">
        <Row k="주소" v={f.addr || "—"} />
        <Row k="전화" v={f.tel || "—"} />
      </Group>
      {f.finAvailable && (
        <Link href={`/whatif?add=${f.histId}`} className="btn w-full no-underline">이 우체국이 문을 닫는다면</Link>
      )}
      <p className="text-[11px] text-ink-3">수집 {dt(f.collectedAt)} · 우정사업본부 우체국 찾기</p>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="group-label">{label}</p>
      <div className="group">{children}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="row"><span className="text-ink-2">{k}</span><span className="tnum text-right font-medium">{v}</span></div>;
}

export function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} aria-label="닫기"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[rgba(118,118,128,.14)] text-ink-2 hover:bg-[rgba(118,118,128,.24)]">
      <svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
    </button>
  );
}

export function fmtPeriod(p?: string | null) {
  return p && p.length === 6 ? `${p.slice(0, 4)}.${p.slice(4)}` : p || "—";
}
