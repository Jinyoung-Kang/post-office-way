/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 2·3 단계 회색은 흰 바탕·회색 바탕 모두 WCAG AA(4.5:1) 이상 — axe 검사로 확인 (#86868b 는 3.6:1 이라 미달)
        ink: { DEFAULT: "#1d1d1f", 2: "#515154", 3: "#6e6e73" },
        surface: "#f5f5f7",
        accent: "#0071e3",
        line: "rgba(0,0,0,0.08)",
      },
      maxWidth: { page: "1024px", wide: "1200px" },
    },
  },
  plugins: [],
};
