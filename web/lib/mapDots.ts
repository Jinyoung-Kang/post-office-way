// 지도 레이어 점 — 지도 SDK 오버레이에 넣을 DOM 을 만듦 (React·지도 SDK 와 무관 — document 를 흉내 내 vitest 로 시험)
// 누를 수 있는 점은 키보드로도(초점·Enter·Space)
import type { Bank, CarePlace, Facility } from "@/lib/api";
import { careHoursText, isBankEvaluable } from "@/lib/rules";

export const FAC_TONE: Record<string, string> = { fin: "#ff9500", other: "#8e8e93", c365: "#34c759" };
export const BANK_TONE = "#af52de";
export const CARE_TONE = { PHARMACY: "#30b0c7", CLINIC: "#ff2d55" } as const;

export function facilityDot(f: Facility, onPick: (f: Facility) => void): HTMLElement {
  const tone = f.finAvailable ? "fin" : f.postDiv === 3 ? "c365" : "other";
  const div = document.createElement("div");
  div.className = "fac-dot";
  div.style.background = FAC_TONE[tone];
  div.title = `${f.name} (${f.divLabel})`;
  div.setAttribute("role", "button");
  div.setAttribute("aria-label", `${f.name} ${f.divLabel}`);
  div.tabIndex = 0;
  div.addEventListener("click", (e) => { e.stopPropagation(); onPick(f); });
  div.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onPick(f); }
  });
  return div;
}

export function bankDot(p: Bank, onPick?: (b: Bank) => void): HTMLElement {
  const div = document.createElement("div");
  div.className = "fac-dot";
  div.style.background = BANK_TONE;
  div.style.borderRadius = "3px";
  // 은행(새마을금고·저축은행 제외)만 영향평가 대상 — 누를 수 있다는 것을 제목으로 알림
  const evaluable = isBankEvaluable(p);
  div.title = `${p.name} · ${p.brand || (p.category || "").split(" > ").pop()}${evaluable && onPick ? " — 눌러서 문을 닫으면 영향 보기" : ""}`;
  if (evaluable) {
    div.style.cursor = "pointer";
    div.addEventListener("click", (e) => { e.stopPropagation(); onPick?.(p); });
  }
  return div;
}

export function careDot(p: CarePlace): HTMLElement {
  const div = document.createElement("div");
  div.className = "care-dot";
  div.style.background = CARE_TONE[p.kind];
  const hours = careHoursText(p.hours);
  div.title = `${p.name} (${p.divName || ""})${hours ? ` — ${hours}` : ""}`;
  return div;
}
