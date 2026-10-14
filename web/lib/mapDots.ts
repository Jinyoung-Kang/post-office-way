// 지도 레이어 점 — 지도 SDK 오버레이에 넣을 DOM 을 만듦 (React·지도 SDK 와 무관 — document 를 흉내 내 vitest 로 시험)
// 누를 수 있는 점은 키보드로도(초점·Enter·Space)
import type { Bank, CarePlace, Facility } from "@/lib/api";
import { careHoursText, isBankEvaluable } from "@/lib/rules";

export const FAC_TONE: Record<string, string> = { fin: "#ff9500", other: "#8e8e93", c365: "#34c759" };
export const BANK_TONE = "#af52de";
export const CARE_TONE = { PHARMACY: "#30b0c7", CLINIC: "#ff2d55" } as const;

// 누를 수 있는 점 — 마우스뿐 아니라 키보드로도: 단추 역할·이름·초점(Tab), Enter·Space 로 고름.
// 지도 클릭(빈 곳을 누르면 말풍선 닫기)으로 번지지 않게 전파를 막음
export function makePickable(el: HTMLElement, label: string, onPick: () => void): HTMLElement {
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", label);
  el.tabIndex = 0;
  el.addEventListener("click", (e) => { e.stopPropagation(); onPick(); });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onPick(); }
  });
  return el;
}

export function facilityDot(f: Facility, onPick: (f: Facility) => void): HTMLElement {
  const tone = f.finAvailable ? "fin" : f.postDiv === 3 ? "c365" : "other";
  const div = document.createElement("div");
  div.className = "fac-dot";
  div.style.background = FAC_TONE[tone];
  div.title = `${f.name} (${f.divLabel})`;
  return makePickable(div, `${f.name} ${f.divLabel}`, () => onPick(f));
}

export function bankDot(p: Bank, onPick?: (b: Bank) => void): HTMLElement {
  const div = document.createElement("div");
  div.className = "fac-dot";
  div.style.background = BANK_TONE;
  div.style.borderRadius = "3px";
  // 은행(새마을금고·저축은행 제외)만 영향평가 대상 — 누를 수 있다는 것을 제목으로 알리고, 시설 점처럼 키보드로도
  const pickable = isBankEvaluable(p) && !!onPick;
  div.title = `${p.name} · ${p.brand || (p.category || "").split(" > ").pop()}${pickable ? " — 눌러서 문을 닫으면 영향 보기" : ""}`;
  if (pickable) {
    div.style.cursor = "pointer";
    makePickable(div, `${p.name} — 문을 닫으면 영향 보기`, () => onPick(p));
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
