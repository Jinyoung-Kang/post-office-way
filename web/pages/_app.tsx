import type { AppProps } from "next/app";
import Head from "next/head";
import "@/styles/globals.css";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>우체국 접근성 아틀라스</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <meta name="theme-color" content="#f5f5f7" />
        <meta name="description" content="우체국 시설과 SGIS 인구·경계 통계로 계산한 지역별 우체국(금융) 접근성 지표" />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
