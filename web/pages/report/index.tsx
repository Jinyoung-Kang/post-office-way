import Link from "next/link";
import { useEffect, useState } from "react";
import Layout, { Card, Hero } from "@/components/Layout";
import { TableSkeleton } from "@/components/Skeleton";
import { cachedApi, type Region } from "@/lib/api";

// ③ 지역 보고서 고르기 — 시도별 시군구 목록
export default function ReportIndex() {
  const [regions, setRegions] = useState<Region[] | null>(null);
  useEffect(() => {
    cachedApi<{ items: Region[] }>("/meta/regions", 600_000).then((r) => setRegions(r.items)).catch(() => setRegions([]));
  }, []);
  return (
    <Layout title="지역 보고서">
      <Hero eyebrow="지역 보고서" title="시군구 한 곳을 한 장으로"
        sub="우체국 접근성·걸어서 가는 거리·지켜야 할 우체국·은행 지점이 닫힐 때의 영향·읍면동 비교를 한 장에 모읍니다. 인쇄하거나 PDF 로 저장해 회의 자료로 쓸 수 있습니다." />
      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        {!regions ? <div className="card p-6"><TableSkeleton rows={8} /></div> : regions.map((s) => (
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
