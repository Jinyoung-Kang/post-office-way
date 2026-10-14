import Link from "next/link";
import Layout, { Card, Empty, ErrorBox, Hero } from "@/components/Layout";
import { TableSkeleton } from "@/components/Skeleton";
import { useRegions } from "@/hooks/useRegions";
import { regionsErrorText } from "@/lib/regions";

// ③ 지역 보고서 고르기 — 시도별 시군구 목록
export default function ReportIndex() {
  // 실패를 빈 목록으로 바꾸면 빈 화면만 남았음 — 받는 중 · 오류 · 목록 없음을 나눠 표시
  const regions = useRegions();
  return (
    <Layout title="지역 보고서">
      <Hero title="지역 보고서"
        sub="우체국 접근성·걸어서 가는 거리·지켜야 할 우체국·은행 지점이 닫힐 때의 영향·읍면동 비교를 한 장에 모읍니다. 인쇄하거나 PDF 로 저장해 회의 자료로 쓸 수 있습니다." />
      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        {regions.loading ? <div className="card p-6"><TableSkeleton rows={8} /></div>
          : regions.error ? <ErrorBox error={regionsErrorText(regions.error)} />
          : !regions.items.length ? <Empty>보고서를 만들 지역이 없습니다 (행정구역 경계를 아직 안 받았다면 make sgis).</Empty>
          : regions.items.map((s) => (
          <Card key={s.admCd} title={s.admNm}>
            <ul className="flex flex-wrap gap-2">{s.sigungu.map((g) => (
              <li key={g.admCd}><Link href={`/report/${g.admCd}`} className="badge badge-info no-underline hover:bg-white">{g.admNm}</Link></li>
            ))}</ul>
          </Card>
        ))}
      </div>
    </Layout>
  );
}
