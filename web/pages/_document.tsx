import { Head, Html, Main, NextScript } from "next/document";

// 문서 언어를 한국어로 — 화면 낭독기가 올바른 발음 규칙을 쓰고, 번역·검색이 언어를 알 수 있게 (axe html-has-lang)
export default function Document() {
  return (
    <Html lang="ko">
      <Head />
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
