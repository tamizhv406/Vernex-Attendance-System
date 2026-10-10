// Design tokens for the whole app live here: colours, radii, shadows, type and motion.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["\"Plus Jakarta Sans\"", "Inter", "\"Segoe UI\"", "Roboto", "Arial", "Helvetica", "sans-serif"]
      },
      colors: {
        // Page background, primary text, hairlines.
        canvas: "#F1F2F4",
        ink: { DEFAULT: "#0E1116", soft: "#1F2530", muted: "#5B6472" },
        line: "#E5E7EB",
        // The one brand accent.
        brand: { 50: "#EEF4FF", 100: "#DCE8FF", 200: "#BCD2FF", 500: "#3B7BFF", 600: "#2563EB", 700: "#1D4FD8" }
      },
      borderRadius: {
        "4xl": "2rem"
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,.04), 0 10px 28px -16px rgba(16,24,40,.14)",
        float: "0 18px 48px -18px rgba(16,24,40,.30)",
        brand: "0 10px 24px -8px rgba(37,99,235,.55)"
      },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "sheet-up": { from: { opacity: "0", transform: "translateY(24px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } }
      },
      animation: {
        "fade-up": "fade-up .25s ease-out both",
        "sheet-up": "sheet-up .22s ease-out both",
        shimmer: "shimmer 1.6s linear infinite"
      }
    }
  },
  plugins: []
};
