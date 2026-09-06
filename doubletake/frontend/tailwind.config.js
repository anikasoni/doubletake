/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Primary dark — text and headers.
        ink: "#1B2430",
        // Page background.
        paper: "#FAF9F6",
        // Card / panel background, one step off paper.
        "paper-raised": "#F1EFE9",
        // Borders and dividers — warm grey, not cool grey.
        rule: "#D8D3C7",
        // State signals.
        "signal-alert": "#A8493F", // contradiction / escalation
        "signal-resolved": "#4A6656", // resolved / confirmed
        "signal-pending": "#8B7355", // awaiting review (muted amber-brown)
      },
      fontFamily: {
        // Headings and large numeric displays.
        serif: ['"Source Serif 4"', "Lora", "Georgia", "serif"],
        // Body text, labels, UI chrome.
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "sans-serif"],
      },
      fontWeight: {
        // Headings are always weight 600.
        heading: "600",
      },
      borderRadius: {
        // Ledger tool, not a consumer app — keep corners nearly square.
        none: "0",
        sm: "2px",
        DEFAULT: "3px",
        md: "4px",
      },
      borderColor: {
        DEFAULT: "#D8D3C7",
      },
    },
  },
  plugins: [],
};
