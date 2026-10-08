// 웹 린트 — React Hook 규칙(호출 순서·의존성 배열)과 TypeScript 파서만. 화면 로직을 Hook 으로 옮길 때
// 의존성 배열 실수(낡은 값·무한 재요청)를 기계로 잡기 위함. 서식은 다루지 않음.
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/**"] },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { parser: tseslint.parser },
    // @typescript-eslint 는 규칙을 켜지 않고 등록만 — 코드의 eslint-disable 주석이 가리키는 규칙 이름을 알게
    plugins: { "react-hooks": reactHooks, "@typescript-eslint": tseslint.plugin },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
);
