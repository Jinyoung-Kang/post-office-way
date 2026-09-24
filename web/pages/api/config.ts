import type { NextApiRequest, NextApiResponse } from "next";

// 브라우저에 가도 되는 유일한 키(카카오 JavaScript 키)만 내려줍니다. 도메인 등록이 보호 수단.
export default function handler(_req: NextApiRequest, res: NextApiResponse) {
  res.setHeader("Cache-Control", "no-store");
  const key = (process.env["KAKAO_JS_KEY"] || process.env["NEXT_PUBLIC_KAKAO_JS_KEY"] || "").trim();
  // .env 에서 값이 비어 있으면 compose 가 줄 끝 주석을 값으로 넘기는 경우가 있어 걸러냄
  res.status(200).json({ kakaoJsKey: key.startsWith("#") ? "" : key });
}
