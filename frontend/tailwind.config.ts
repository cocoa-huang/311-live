import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#17211c",
        field: "#f5f3ec",
        signal: "#1b7f5c",
        civic: "#285d8f",
        caution: "#c77724",
      },
    },
  },
  plugins: [],
};

export default config;
