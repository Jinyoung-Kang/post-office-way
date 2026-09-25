/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from "react";
import { api, qs, type Bank, type CarePlace, type Facility, type Feature, type Page } from "@/lib/api";
import { loadKakao, toPaths } from "@/lib/kakao";

export type Style = { fill: string; opacity?: number; stroke?: string };
export type Marker = { lat: number; lon: number; label: string; tone: "removed" | "new" | "focus" };
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
  geomKey?: string;              // 바뀌면 폴리곤을 새로 만들고 범위에 맞춤. 같으면 색만 다시 칠함(지표 변경 1초 안 — FR-501)
  focusCd?: string | null;       // 이 지역으로 확대
  padding?: [number, number, number, number]; // 떠 있는 패널을 피해 맞출 여백 (상, 우, 하, 좌 px)
  className?: string;
};

const FAC_TONE: Record<string, string> = { fin: "#ff9500", other: "#8e8e93", c365: "#34c759" };
const MARKER_TONE: Record<Marker["tone"], string> = { removed: "#d70015", new: "#1d8a3a", focus: "#1d1d1f" };
const BANK_TONE = "#af52de";
const CARE_TONE = { PHARMACY: "#30b0c7", CLINIC: "#ff2d55" } as const;
const WEEK = ["", "월", "화", "수", "목", "금", "토", "일", "공휴일"];

function esc(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

export default function AtlasMap<P extends { admCd: string; admNm: string }>(props: Props<P>) {
  const { features, styleOf, tooltipOf, selected, onSelect, facilities, onFacility, banks, care, markers, geomKey, focusCd,
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
  const cb = useRef({ styleOf, tooltipOf, onSelect, selected, onFacility, padding });
  cb.current = { styleOf, tooltipOf, onSelect, selected, onFacility, padding };
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [facNote, setFacNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadKakao().then((kakao) => {
      if (cancelled || !el.current) return;
      kakaoRef.current = kakao;
      map.current = new kakao.maps.Map(el.current, { center: new kakao.maps.LatLng(36.3, 127.8), level: 12 });
      map.current.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHTBOTTOM);
      tip.current = new kakao.maps.CustomOverlay({ yAnchor: 1.35, zIndex: 10 });
      setReady(true);
    }).catch((e) => setErr(e.message));
    return () => { cancelled = true; };
  }, []);

  function fit(shapes: any[]) {
    const kakao = kakaoRef.current;
    const b = new kakao.maps.LatLngBounds();
    shapes.forEach((s) => s.getPath().forEach((ring: any) => (Array.isArray(ring) ? ring : [ring]).forEach((ll: any) => b.extend(ll))));
    if (!b.isEmpty()) {
      const [t, r, bo, l] = cb.current.padding;
      map.current.setBounds(b, t, r, bo, l);
    }
  }

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
    polys.current.clear();
    const all: any[] = [];
    for (const f of features) {
      if (!f.geometry) continue;
      const entry = { shapes: [] as any[], props: f.properties };
      entry.shapes = toPaths(kakao, f.geometry).map((path) => {
        const poly = new kakao.maps.Polygon({ map: map.current, path, strokeWeight: 1, strokeColor: "#ffffff",
          strokeOpacity: 1, fillColor: "#e5e5ea", fillOpacity: 0.75 });
        kakao.maps.event.addListener(poly, "mouseover", (e: any) => hover(entry.props, e.latLng, true));
        kakao.maps.event.addListener(poly, "mousemove", (e: any) => tip.current?.setPosition(e.latLng));
        kakao.maps.event.addListener(poly, "mouseout", () => hover(entry.props, null, false));
        kakao.maps.event.addListener(poly, "click", () => { tip.current?.setMap(null); cb.current.onSelect?.(entry.props.admCd); });
        return poly;
      });
      all.push(...entry.shapes);
      polys.current.set(f.properties.admCd, entry);
    }
    builtKey.current = key;
    paint();
    if (all.length && !focusCd) fit(all);
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
  }, [ready, focusCd, features]);

  function paint() {
    polys.current.forEach(({ shapes, props: p }, cd) => {
      const st = cb.current.styleOf(p);
      const sel = cd === cb.current.selected;
      shapes.forEach((s) => s.setOptions({ fillColor: st.fill, fillOpacity: st.opacity ?? 0.8,
        strokeColor: sel ? "#1d1d1f" : st.stroke || "#ffffff", strokeWeight: sel ? 3 : 1, zIndex: sel ? 5 : 1 }));
    });
  }

  function hover(p: P, latLng: any, on: boolean) {
    const entry = polys.current.get(p.admCd);
    if (!entry) return;
    const st = cb.current.styleOf(p);
    const sel = p.admCd === cb.current.selected;
    entry.shapes.forEach((s) => s.setOptions({ fillOpacity: on ? Math.min((st.opacity ?? 0.8) + 0.12, 1) : st.opacity ?? 0.8,
      strokeColor: on || sel ? "#1d1d1f" : st.stroke || "#ffffff", strokeWeight: on || sel ? 2 : 1 }));
    if (on && latLng) {
      const body = cb.current.tooltipOf ? cb.current.tooltipOf(p) : "";
      tip.current.setContent(`<div class="map-tip"><b>${esc(p.admNm)}</b>${body ? `<br/>${body}` : ""}</div>`);
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
