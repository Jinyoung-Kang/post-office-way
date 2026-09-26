import Link from "next/link";
import Layout from "@/components/Layout";

// 없는 주소 — 기본 영문 404 대신 서비스 안에서 길을 찾을 수 있게
export default function NotFound() {
  return (
    <Layout title="페이지를 찾을 수 없음">
      <section className="mx-auto max-w-page px-4 py-24 text-center">
        <p className="eyebrow mb-2">404</p>
        <h1 className="hero-title">이 길은 없습니다.</h1>
        <p className="hero-sub mx-auto mt-4 max-w-xl">주소가 바뀌었거나 잘못 입력되었습니다. 아래에서 다시 시작해 보세요.</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link href="/overview" className="btn btn-lg no-underline">한눈에 보기</Link>
          <Link href="/" className="link text-[17px]">지도 ›</Link>
          <Link href="/today" className="link text-[17px]">방문 여건 ›</Link>
        </div>
      </section>
    </Layout>
  );
}
