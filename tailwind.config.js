/** Tailwind config for the compiled stylesheet (app/static/tailwind.css).
 *  Rebuild after editing templates:  python tools/build_css.py   (needs `pip install pytailwindcss`)
 */
module.exports = {
  darkMode: "class",
  content: ["./app/templates/**/*.html", "./app/static/app.js"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        mint: { DEFAULT: "#00D09C", 50: "#E6FAF5", 600: "#00B386" },
        crimson: { DEFAULT: "#EB5B5B", 50: "#FDEEEE", 600: "#D64545" },
        indigo: { DEFAULT: "#5367FF", 50: "#EEF0FF" },
        ink: { 900: "#1E222D", 700: "#44475B", 500: "#7C7E8C", 300: "#B8BAC4" },
        surface: { DEFAULT: "#FFFFFF", 1: "#F8F9FA", line: "#EAECF0", dark: "#121212", card: "#1E222D", darkline: "#2B303D" },
      },
      boxShadow: { card: "0 1px 2px rgba(30,34,45,0.04), 0 4px 16px rgba(30,34,45,0.06)" },
    },
  },
  plugins: [],
};
