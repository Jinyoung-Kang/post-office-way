// vitest — tsconfig 의 '@/…' 경로를 그대로 쓰게 (Hook·화면 로직 테스트가 앱 코드와 같은 import 를 씀)
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
});
