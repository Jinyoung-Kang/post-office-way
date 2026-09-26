/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from "react";
import { api, qs, type Bank, type CarePlace, type Facility, type Feature, type Page } from "@/lib/api";
import { loadKakao, toPaths } from "@/lib/kakao";

export type Style = { fill: string; opacity?: number; stroke?: string };
export type Marker = { lat: number; lon: number; label: string; tone: "removed" | "new" | "focus" };
// 늘 보이는 지역 라벨 (마우스를 올리지 않아도 핵심 값이 보이게) — 대표점에 작은 알약
export type MapLabel = { key: string; lat: number; lon: number; title: string; value?: string; tone?: "dark" | "bad" | "warn" | "good" };
export type FacilityLayer = { finOnly: boolean; types: number[] } | null;
export type CareLayer = { holidayOnly: boolean } | null;

type Props<P extends { admCd: string; admNm: string }> = {
  features: Feature<P>[];
  styleOf: (p: P) => Style;
  tooltipOf?: (p: P) => string;
  selected?: string | null;
  onSelect?: (admCd: string) => void;
  facilities?: FacilityLayer;
  onFacility?: (f: Facility) => void;
  banks?: boolean;               // ④ 은행·금고 지점 레이어
  care?: CareLayer;              // ⑦ 약국·의원 레이어 (공휴일 진료만 거를 수 있음)
  markers?: Marker[];
  labels?: MapLabel[];
  pinOnClick?: boolean;          // 지역을 누르면(터치 포함) 정보 말풍선을 고정 — onSelect 가 없을 때 기본
  geomKey?: string;              // 바뀌면 폴리곤을 새로 만들고 범위에 맞춤. 같으면 색만 다시 칠함(지표 변경 1초 안 — FR-501)
  focusCd?: string | null;       // 이 지역으로 확대
  padding?: [number, number, number, number]; // 떠 있는 패널을 피해 맞출 여백 (상, 우, 하, 좌 px)
  className?: string;
};

const FAC_TONE: Record<string, string> = { fin: "#ff9500", other: "#8e8e93", c365: "#34c759" };
const MARKER_TONE: Record<Marker["tone"], string> = { removed: "#d70015", new: "#18782f", focus: "#1d1d1f" };
const BANK_TONE = "#af52de";
const CARE_TONE = { PHARMACY: "#30b0c7", CLINIC: "#ff2d55" } as const;
const WEEK = ["", "월", "화", "수", "목", "금", "토", "일", "공휴일"];

// 긴 작업을 나눌 때 브라우저에 차례를 넘김 (scheduler.yield 가 있으면 우선순위를 지킨 채로)
function yieldToMain(): Promise<void> {
  const sch = (globalThis as any).scheduler;
  return sch?.yield ? sch.yield() : new Promise((r) => setTimeout(r, 0));
}

function esc(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

export default function AtlasMap<P extends { admCd: string; admNm: string }>(props: Props<P>) {
  const { features, styleOf, tooltipOf, selected, onSelect, facilities, onFacility, banks, care, markers, labels, pinOnClick, geomKey, focusCd,
    padding = [24, 24, 24, 24], className } = props;
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const kakaoRef = useRef<any>(null);
  const polys = useRef<Map<string, { shapes: any[]; props: P }>>(new Map());
  const builtKey = useRef<string | null>(null);
  const focusedCd = useRef<string | null>(null);
  const tip = useRef<any>(null);
  const facOverlays = useRef<any[]>([]);
  const markerOverlays = useRef<any[]>([]);
  const bankOverlays = useRef<any[]>([]);
  const careOverlays = useRef<any[]>([]);
  const labelOverlays = useRef<any[]>([]);
  const pinned = useRef<string | null>(null);
  const shapeClickAt = useRef(0);   // 도형 클릭 뒤 같은 클릭으로 지도 click 이 또 오면 무시(카카오는 둘 다 보냄)
  const cb = useRef({ styleOf, tooltipOf, onSelect, selected, onFacility, padding, pin: pinOnClick ?? !onSelect });
  cb.current = { styleOf, tooltipOf, onSelect, selected, onFacility, padding, pin: pinOnClick ?? !onSelect };
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [facNote, setFacNote] = useState<string | null>(null);
  const [built, setBuilt] = useState(0);   // 폴리곤을 다 만든 횟수 — 나눠 만들기가 끝난 뒤 확대 등이 다시 돌게

  useEffect(() => {
    let cancelled = false;
    loadKakao().then((kakao) => {
      if (cancelled || !el.current) return;
      kakaoRef.current = kakao;
      map.current = new kakao.maps.Map(el.current, { center: new kakao.maps.LatLng(36.3, 127.8), level: 12 });
      map.current.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHTBOTTOM);
      tip.current = new kakao.maps.CustomOverlay({ yAnchor: 1.35, zIndex: 10 });
      // 빈 곳을 누르면 고정한 말풍선 닫기
      kakao.maps.event.addListener(map.current, "click", () => {
        if (performance.now() - shapeClickAt.current < 300) return;
        pinned.current = null; tip.current?.setMap(null);
      });
      setReady(true);
    }).catch((e) => setErr(e.message));
    return () => { cancelled = true; };
  }, []);

  function boundsOf(shapes: any[]) {
    const b = new kakaoRef.current.maps.LatLngBounds();
    shapes.forEach((s) => s.getPath().forEach((ring: any) => (Array.isArray(ring) ? ring : [ring]).forEach((ll: any) => b.extend(ll))));
    return b;
  }

  function fit(shapes: any[]) {
    const b = boundsOf(shapes);
    if (!b.isEmpty()) {
      const [t, r, bo, l] = cb.current.padding;
      map.current.setBounds(b, t, r, bo, l);
    }
  }

  // 컨테이너 크기가 바뀌면(패널 열고 닫기·창 크기) 지도를 다시 배치하고 다시 칠함.
  // 탭이 다시 보일 때도 다시 칠함 — 일부 브라우저는 숨은 동안의 벡터 그리기를 건너뜀
  useEffect(() => {
    if (!ready || !el.current) return;
    let raf = 0;
    const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { map.current?.relayout(); paint(); }); };
    const ro = new ResizeObserver(redraw);
    ro.observe(el.current);
    const onVis = () => { if (document.visibilityState === "visible") redraw(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { ro.disconnect(); document.removeEventListener("visibilitychange", onVis); cancelAnimationFrame(raf); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // 폴리곤: geomKey 가 같고 지역 목록이 같으면 속성만 바꾸고 다시 칠함
  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    const key = geomKey ?? "";
    const same = builtKey.current === key && features.length === polys.current.size
      && features.every((f) => polys.current.has(f.properties.admCd));
    if (same) {
      features.forEach((f) => { const e = polys.current.get(f.properties.admCd); if (e) e.props = f.properties; });
      paint();
      return;
    }
    polys.current.forEach(({ shapes }) => shapes.forEach((s) => s.setMap(null)));
    polys.current = new Map();
    pinned.current = null;
    tip.current?.setMap(null);
    const next = new Map<string, { shapes: any[]; props: P }>();
    const all: any[] = [];
    const make = (f: (typeof features)[number]) => {
      if (!f.geometry) return;
      const entry = { shapes: [] as any[], props: f.properties };
      // 처음엔 지도에 붙이지 않고 만든 뒤, 화면 이동이 끝난 다음 한꺼번에 붙임(아래 attach)
      entry.shapes = toPaths(kakao, f.geometry).map((path) => {
        const poly = new kakao.maps.Polygon({ path, strokeWeight: 1, strokeColor: "#ffffff",
          strokeOpacity: 1, fillColor: "#e5e5ea", fillOpacity: 0.75 });
        kakao.maps.event.addListener(poly, "mouseover", (e: any) => hover(entry.props, e.latLng, true));
        kakao.maps.event.addListener(poly, "mousemove", (e: any) => { if (!pinned.current) tip.current?.setPosition(e.latLng); });
        kakao.maps.event.addListener(poly, "mouseout", () => hover(entry.props, null, false));
        kakao.maps.event.addListener(poly, "click", (e: any) => {
          shapeClickAt.current = performance.now();
          if (cb.current.pin) { pin(entry.props, e.latLng); return; }
          tip.current?.setMap(null);
          cb.current.onSelect?.(entry.props.admCd);
        });
        return poly;
      });
      all.push(...entry.shapes);
      next.set(f.properties.admCd, entry);
    };
    // 폴리곤을 먼저 붙이고 setBounds 하면 일부 브라우저(특히 고해상도·Safari)에서 이동 뒤 벡터를 다시 그리지 않아
    // 마우스를 올려야 색이 보였음 → 화면을 먼저 맞추고 이동이 끝난(idle) 뒤 붙여서 칠함. idle 이 안 오면 400ms 뒤 붙임
    let cancelled = false, built = false, attached = false, timer: ReturnType<typeof setTimeout> | undefined;
    const attach = () => {
      if (attached) return;
      attached = true;
      kakao.maps.event.removeListener(map.current, "idle", attach);
      all.forEach((s) => s.setMap(map.current));
      paint();
      requestAnimationFrame(() => paint());
    };
    // 시군구 252곳이면 좌표 수만 개를 LatLng·Polygon 으로 만드느라 느린 기기에서 0.5초 넘게 한 번에 막혔음(긴 작업) →
    // 약 12ms 씩 나눠 만들고 사이에 브라우저에 양보해 스크롤·클릭이 끼어들 수 있게 함
    (async () => {
      let i = 0;
      while (i < features.length) {
        const until = performance.now() + 12;
        while (i < features.length && performance.now() < until) make(features[i++]);
        if (i < features.length) await yieldToMain();
        if (cancelled) return;
      }
      polys.current = next;
      builtKey.current = key;
      built = true;
      setBuilt((n) => n + 1);
      if (all.length && !focusCd) {
        kakao.maps.event.addListener(map.current, "idle", attach);
        fit(all);
        timer = setTimeout(attach, 400);
      } else attach();
    })();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      kakao.maps.event.removeListener(map.current, "idle", attach);
      if (built && !attached) attach();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, features, geomKey]);

  useEffect(() => { if (ready) paint(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [styleOf, selected, ready]);

  // 특정 지역으로 확대 (순위 화면에서 넘어온 경우 등) — 한 번만. 이후 지표를 바꿔도 사용자가 옮긴 화면을 유지
  useEffect(() => {
    if (!focusCd) { focusedCd.current = null; return; }
    if (!ready || focusedCd.current === focusCd) return;
    const e = polys.current.get(focusCd);
    if (e) { fit(e.shapes); focusedCd.current = focusCd; }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focusCd, features, built]);

  function paint() {
    polys.current.forEach(({ shapes, props: p }, cd) => {
      const st = cb.current.styleOf(p);
      const sel = cd === cb.current.selected;
      shapes.forEach((s) => s.setOptions({ fillColor: st.fill, fillOpacity: st.opacity ?? 0.8,
        strokeColor: sel ? "#1d1d1f" : st.stroke || "#ffffff", strokeWeight: sel ? 3 : 1, zIndex: sel ? 5 : 1 }));
    });
  }

  function tipHtml(p: P) {
    const body = cb.current.tooltipOf ? cb.current.tooltipOf(p) : "";
    return `<div class="map-tip">${pinned.current ? '<span class="map-tip-x" aria-hidden="true">✕</span>' : ""}<b>${esc(p.admNm)}</b>${body ? `<br/>${body}` : ""}</div>`;
  }

  // 누르면(터치 포함) 말풍선 고정 — 마우스를 치워도 남고, 빈 곳이나 같은 지역을 다시 누르면 닫힘
  function pin(p: P, latLng: any) {
    if (pinned.current === p.admCd) { pinned.current = null; tip.current.setMap(null); return; }
    pinned.current = p.admCd;
    tip.current.setContent(tipHtml(p));
    tip.current.setPosition(latLng);
    tip.current.setMap(map.current);
  }

  function hover(p: P, latLng: any, on: boolean) {
    const entry = polys.current.get(p.admCd);
    if (!entry) return;
    const st = cb.current.styleOf(p);
    const sel = p.admCd === cb.current.selected;
    entry.shapes.forEach((s) => s.setOptions({ fillOpacity: on ? Math.min((st.opacity ?? 0.8) + 0.12, 1) : st.opacity ?? 0.8,
      strokeColor: on || sel ? "#1d1d1f" : st.stroke || "#ffffff", strokeWeight: on || sel ? 2 : 1 }));
    if (pinned.current) return;          // 고정한 말풍선이 있으면 마우스로 바꾸지 않음
    if (on && latLng) {
      tip.current.setContent(tipHtml(p));
      tip.current.setPosition(latLng);
      tip.current.setMap(map.current);
    } else {
      tip.current.setMap(null);
    }
  }

  // 시설 레이어 — 확대 수준 10(도 단위) 이하에서 화면 범위만 조회 (최대 3,000개)
  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    let seq = 0;
    const clear = () => { facOverlays.current.forEach((o) => o.setMap(null)); facOverlays.current = []; };
    if (!facilities) { clear(); setFacNote(null); return; }
    const load = async () => {
      const my = ++seq;
      if (map.current.getLevel() > 10) { clear(); setFacNote("확대하면 시설이 보입니다"); return; }
      const b = map.current.getBounds();
      const sw = b.getSouthWest(), ne = b.getNorthEast();
      try {
        const res = await api<Page<Facility>>(`/facilities${qs({
          bbox: [sw.getLng(), sw.getLat(), ne.getLng(), ne.getLat()].map((v: number) => v.toFixed(5)).join(","),
          types: facilities.types.join(","), finOnly: facilities.finOnly || undefined, size: 3000 })}`);
        if (my !== seq) return;
        clear();
        for (const f of res.items) {
          const tone = f.finAvailable ? "fin" : f.postDiv === 3 ? "c365" : "other";
          const div = document.createElement("div");
          div.className = "fac-dot";
          div.style.background = FAC_TONE[tone];
          div.title = `${f.name} (${f.divLabel})`;
          div.setAttribute("role", "button");
          div.setAttribute("aria-label", `${f.name} ${f.divLabel}`);
          div.addEventListener("click", (e) => { e.stopPropagation(); cb.current.onFacility?.(f); });
          facOverlays.current.push(new kakao.maps.CustomOverlay({ map: map.current, position: new kakao.maps.LatLng(f.lat, f.lon),
            content: div, zIndex: 6, clickable: true }));
        }
        setFacNote(res.total > res.items.length ? `시설 ${res.items.length.toLocaleString()} / ${res.total.toLocaleString()}` : `시설 ${res.total.toLocaleString()}곳`);
      } catch (e: any) { setFacNote(`시설 조회 실패: ${e.message}`); }
    };
    load();
    const h = () => load();
    kakao.maps.event.addListener(map.current, "idle", h);
    return () => { kakao.maps.event.removeListener(map.current, "idle", h); seq++; clear(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, facilities?.finOnly, facilities?.types.join(",")]);

  // 은행·금고 지점 레이어 — 확대 수준 9 이하에서 화면 범위만 (보라 사각 점)
  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    let seq = 0;
    const clear = () => { bankOverlays.current.forEach((o) => o.setMap(null)); bankOverlays.current = []; };
    if (!banks) { clear(); return; }
    const load = async () => {
      const my = ++seq;
      if (map.current.getLevel() > 9) { clear(); return; }
      const b = map.current.getBounds();
      const sw = b.getSouthWest(), ne = b.getNorthEast();
      try {
        const res = await api<{ items: Bank[] }>(`/banks${qs({ bbox: [sw.getLng(), sw.getLat(), ne.getLng(), ne.getLat()].map((v: number) => v.toFixed(5)).join(","), size: 3000 })}`);
        if (my !== seq) return;
        clear();
        for (const p of res.items) {
          const div = document.createElement("div");
          div.className = "fac-dot";
          div.style.background = BANK_TONE;
          div.style.borderRadius = "3px";
          div.title = `${p.name} · ${(p.category || "").split(" > ").pop()}`;
          bankOverlays.current.push(new kakao.maps.CustomOverlay({ map: map.current, position: new kakao.maps.LatLng(p.lat, p.lon),
            content: div, zIndex: 5 }));
        }
      } catch { /* 레이어는 보조 정보 — 실패해도 지도는 유지 */ }
    };
    load();
    const h = () => load();
    kakao.maps.event.addListener(map.current, "idle", h);
    return () => { kakao.maps.event.removeListener(map.current, "idle", h); seq++; clear(); };
  }, [ready, banks]);

  // 약국·의원 레이어 — 확대 수준 7 이하(시군구 안)에서 화면 범위만. 마름모 점, 누르면 진료시간
  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    let seq = 0;
    const clear = () => { careOverlays.current.forEach((o) => o.setMap(null)); careOverlays.current = []; };
    if (!care) { clear(); return; }
    const load = async () => {
      const my = ++seq;
      if (map.current.getLevel() > 7) { clear(); setFacNote("확대하면 약국·의원이 보입니다"); return; }
      const b = map.current.getBounds();
      const sw = b.getSouthWest(), ne = b.getNorthEast();
      try {
        const res = await api<{ items: CarePlace[] }>(`/care${qs({ bbox: [sw.getLng(), sw.getLat(), ne.getLng(), ne.getLat()]
          .map((v: number) => v.toFixed(5)).join(","), holidayOnly: care.holidayOnly || undefined, size: 3000 })}`);
        if (my !== seq) return;
        clear();
        for (const p of res.items) {
          const div = document.createElement("div");
          div.className = "care-dot";
          div.style.background = CARE_TONE[p.kind];
          const hours = Object.entries(p.hours || {}).filter(([d]) => ["1", "6", "7", "8"].includes(d))
            .map(([d, [a, z]]) => `${WEEK[Number(d)]} ${a.slice(0, 2)}:${a.slice(2)}~${z.slice(0, 2)}:${z.slice(2)}`).join(" · ");
          div.title = `${p.name} (${p.divName || ""})${hours ? ` — ${hours}` : ""}`;
          careOverlays.current.push(new kakao.maps.CustomOverlay({ map: map.current, position: new kakao.maps.LatLng(p.lat, p.lon),
            content: div, zIndex: 4 }));
        }
        setFacNote(`약국·의원 ${res.items.length.toLocaleString()}곳${care.holidayOnly ? " (공휴일 진료)" : ""}`);
      } catch (e: any) { setFacNote(e.message); }
    };
    load();
    const h = () => load();
    kakao.maps.event.addListener(map.current, "idle", h);
    return () => { kakao.maps.event.removeListener(map.current, "idle", h); seq++; clear(); setFacNote(null); };
  }, [ready, care?.holidayOnly, !!care]);

  // 늘 보이는 라벨 — 순위 상위 지역 등 핵심 값만 (많으면 지도가 가려져 10여 개로 제한하는 건 부르는 쪽 몫)
  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    labelOverlays.current.forEach((o) => o.setMap(null));
    const items = (labels || []).map((l) => ({
      pos: new kakao.maps.LatLng(l.lat, l.lon),
      // 화면 폭 추정(글자 수 × 약 7px) — 겹침 판정용
      w: ((l.title.length + (l.value?.length || 0)) * 7 + 28), h: 22,
      ov: new kakao.maps.CustomOverlay({ position: new kakao.maps.LatLng(l.lat, l.lon), yAnchor: 0.5, zIndex: 7, clickable: false,
        content: `<div class="map-label ${l.tone ? `map-label-${l.tone}` : ""}"><b>${esc(l.title)}</b>${l.value ? `<span>${esc(l.value)}</span>` : ""}</div>` }),
    }));
    labelOverlays.current = items.map((x) => x.ov);
    // 겹치는 라벨은 우선순위(배열 순서)가 낮은 쪽을 숨김 — 확대하면 다시 나타남
    const declutter = () => {
      const proj = map.current.getProjection();
      const kept: { x: number; y: number; w: number; h: number }[] = [];
      for (const it of items) {
        const pt = proj.containerPointFromCoords(it.pos);
        const box = { x: pt.x - it.w / 2, y: pt.y - it.h / 2, w: it.w, h: it.h };
        const hit = kept.some((k) => box.x < k.x + k.w + 4 && k.x < box.x + box.w + 4 && box.y < k.y + k.h + 2 && k.y < box.y + box.h + 2);
        if (hit) it.ov.setMap(null); else { kept.push(box); it.ov.setMap(map.current); }
      }
    };
    declutter();
    kakao.maps.event.addListener(map.current, "idle", declutter);
    return () => { kakao.maps.event.removeListener(map.current, "idle", declutter); items.forEach((x) => x.ov.setMap(null)); };
  }, [ready, labels]);

  useEffect(() => {
    const kakao = kakaoRef.current;
    if (!ready || !kakao) return;
    markerOverlays.current.forEach((o) => o.setMap(null));
    markerOverlays.current = (markers || []).map((m) => new kakao.maps.CustomOverlay({ map: map.current,
      position: new kakao.maps.LatLng(m.lat, m.lon), yAnchor: 1, zIndex: 8,
      content: `<div class="pin" style="--pin:${MARKER_TONE[m.tone]}"><span>${esc(m.label)}</span></div>` }));
  }, [ready, markers]);

  return (
    // className 에 absolute 가 있으면 relative 를 붙이지 않음 (둘이 겹치면 CSS 순서상 relative 가 이겨 높이 0)
    <div className={`${/\b(absolute|fixed)\b/.test(className || "") ? "" : "relative"} ${className || ""}`}>
      <div ref={el} className="absolute inset-0 bg-[#e8e8ed]" />
      {err && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-6 text-center">
          <div className="glass max-w-md p-5 text-[14px]">
            <p className="text-[17px] font-semibold">지도를 표시할 수 없습니다</p>
            <p className="mt-1 text-ink-2">{err}</p>
          </div>
        </div>
      )}
      {facNote && <div className="glass absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full px-3 py-1 text-[12px] text-ink-2">{facNote}</div>}
    </div>
  );
}

export const BANK_LEGEND = { label: "은행·금고 지점", color: BANK_TONE };
export const CARE_LEGEND = [{ label: "약국", color: CARE_TONE.PHARMACY }, { label: "의원·병원·보건소", color: CARE_TONE.CLINIC }];
export const FACILITY_LEGEND = [
  { label: "금융 가능 우체국", color: FAC_TONE.fin },
  { label: "365코너", color: FAC_TONE.c365 },
  { label: "기타 시설", color: FAC_TONE.other },
];
