/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#1d1d1f", 2: "#6e6e73", 3: "#86868b" },
        surface: "#f5f5f7",
        accent: "#0071e3",
        line: "rgba(0,0,0,0.08)",
      },
      maxWidth: { page: "1024px", wide: "1200px" },
    },
  },
  plugins: [],
};
