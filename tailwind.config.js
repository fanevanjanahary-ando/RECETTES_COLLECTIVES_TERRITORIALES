const avecFormulaires = process.env.AVEC_FORMULAIRES !== "0";
const paletteNeutre = {
  50: "#F8FAFC",
  100: "#F1F5F9",
  200: "#E2E8F0",
  300: "#CBD5E1",
  400: "#9CA3AF",
  500: "#6B7280",
  600: "#25272C",
  700: "#1E2024",
  800: "#131417",
  900: "#090A0B",
  950: "#000000",
};

module.exports = {
  content: [
    "./recettes/templates/**/*.html",
    "./recettes/graphiques.py",
    "./recettes/views.py",
    "./recettes/forms.py",
  ],
  theme: {
    extend: {
      colors: {
        emerald: paletteNeutre,
        green: paletteNeutre,
        teal: paletteNeutre,
        lime: paletteNeutre,
      },
      fontFamily: {
        inter: ["Inter", "sans-serif"],
        pjs: ["Plus Jakarta Sans", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: avecFormulaires
    ? [require("@tailwindcss/forms"), require("@tailwindcss/container-queries")]
    : [require("@tailwindcss/container-queries")],
};