import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#1c1917", soft: "#44403c", muted: "#78716c" },
        paper: { DEFAULT: "#faf9f7", card: "#ffffff", line: "#e7e5e4" },
        brand: { DEFAULT: "#b45309", dark: "#92400e", soft: "#fef3c7" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: { card: "0 1px 2px rgba(28,25,23,.06), 0 1px 3px rgba(28,25,23,.08)" },
    },
  },
  plugins: [],
};
export default config;
