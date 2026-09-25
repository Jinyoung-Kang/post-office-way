import type { AppProps } from "next/app";
import Head from "next/head";
import "@/styles/globals.css";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>우체국 가는 길</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <meta name="theme-color" content="#f5f5f7" />
        <meta name="description" content="우체국까지 얼마나 먼지, 오늘 가기 괜찮은지, 문을 닫으면 누가 무엇을 잃는지 — 전국 우체국 접근성 분석" />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
