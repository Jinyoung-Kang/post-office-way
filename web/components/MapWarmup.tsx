import Head from "next/head";
import { loadKakao } from "@/lib/kakao";

// 지도 화면의 첫 그림(LCP)은 카카오 SDK 가 까는 배경 타일이라 SDK 가 늦을수록 늦음.
// 지도 컴포넌트는 dynamic(ssr: false) 라 하이드레이션 뒤에야 불러지므로, 페이지가 정적으로 가져오는 이 모듈에서
// ① 서버 HTML 에 SDK 출처들로의 preconnect 를 넣고 ② 하이드레이션 렌더 때 바로 SDK 를 받기 시작함.
// 실패는 여기서 삼키고, 지도 컴포넌트의 loadKakao() 가 다시 시도·오류 표시를 맡음.
// 모듈 최상위에서 부르면 Next 가 링크 미리 받기로 지도 페이지 코드를 읽을 때 지도 없는 화면에서도 SDK 를 받았음 →
// 이 컴포넌트가 실제로 그려질 때(하이드레이션 렌더)만. loadKakao 는 한 번만 받으므로 여러 번 불려도 됨
export default function MapWarmup() {
  if (typeof window !== "undefined") loadKakao().catch(() => undefined);
  return (
    <Head>
      {/* SDK(dapi) → 본체·이미지(t1) → 타일(mts) 순서로 받는 출처들 */}
      <link key="pc-dapi" rel="preconnect" href="https://dapi.kakao.com" />
      <link key="pc-t1" rel="preconnect" href="https://t1.daumcdn.net" />
      <link key="pc-mts" rel="preconnect" href="https://mts.daumcdn.net" />
    </Head>
  );
}
