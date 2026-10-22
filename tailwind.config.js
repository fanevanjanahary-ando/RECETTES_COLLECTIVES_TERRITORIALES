const avecFormulaires = process.env.AVEC_FORMULAIRES !== "0";

module.exports = {
  content: [
    "./recettes/templates/**/*.html",
    "./recettes/graphiques.py",
    "./recettes/views.py",
    "./recettes/forms.py",
  ],
  theme: {
    extend: {
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