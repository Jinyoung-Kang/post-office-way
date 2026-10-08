import { Children, Fragment, type ReactNode } from "react";
import { SENTENCE_GAP } from "@/lib/format";

// 설명 글을 문장마다 줄바꿈 — 글 속 문자열 조각만 '마침표 + 공백'에서 나눠 <br/> 를 넣고, 굵게·링크·코드 같은 요소는 그대로 둠.
// 구절 중간에서 줄이 끊기지 않고(데스크톱), 좁은 화면에서는 문장 안에서만 어절 단위로 줄바꿈(전역 keep-all·text-wrap: pretty).
// {a} {b} 처럼 이어진 문자열 조각은 먼저 합쳐, 조각 사이의 문장 경계도 나눔
export default function Sents({ children }: { children: ReactNode }) {
  const merged: ReactNode[] = [];
  for (const c of Children.toArray(children)) {
    const last = merged[merged.length - 1];
    if ((typeof c === "string" || typeof c === "number") && typeof last === "string") merged[merged.length - 1] = last + c;
    else merged.push(typeof c === "number" ? String(c) : c);
  }
  const out: ReactNode[] = [];
  merged.forEach((c, i) => {
    if (typeof c !== "string") { out.push(c); return; }
    c.split(SENTENCE_GAP).forEach((part, j) => {
      if (j > 0) out.push(<br key={`b${i}-${j}`} />);
      if (part) out.push(<Fragment key={`t${i}-${j}`}>{part}</Fragment>);
    });
  });
  return <>{out}</>;
}
