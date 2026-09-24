import { VISIT_BADGE, VISIT_LABEL } from "@/lib/format";

// ⑥ 방문 여건 등급 — 색과 글자를 함께 표시
export default function VisitBadge({ level }: { level: number | null | undefined }) {
  if (level === null || level === undefined) return <span className="badge badge-info">예보 없음</span>;
  return <span className={`badge ${VISIT_BADGE[level]}`}>{VISIT_LABEL[level]}</span>;
}
