import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#111111",
        field: "#F5F5F5",
        signal: "#006B3F",
        civic: "#0067AC",
        caution: "#CC4500",
        brand: "#F5D200",
      },
      fontFamily: {
        sans: ['"Barlow"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"Barlow"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 3px 0 rgba(0,0,0,0.07), 0 1px 2px -1px rgba(0,0,0,0.04)",
      },
      keyframes: {
        "pulse-speaking": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(245,210,0,0.5)" },
          "50%": { boxShadow: "0 0 0 8px rgba(245,210,0,0)" },
        },
        "blink-live": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-speaking": "pulse-speaking 1.6s ease-in-out infinite",
        "blink-live": "blink-live 1.2s ease-in-out infinite",
        "slide-up": "slide-up 0.25s ease-out forwards",
      },
    },
  },
  plugins: [],
};

export default config;
