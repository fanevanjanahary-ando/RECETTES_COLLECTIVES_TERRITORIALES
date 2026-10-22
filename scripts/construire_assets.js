const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const racine = path.resolve(__dirname, "..");
const sortie = path.join(racine, "recettes", "static", "recettes", "vendor");
const polices = path.join(sortie, "polices");
const nm = path.join(racine, "node_modules");

fs.mkdirSync(polices, { recursive: true });

fs.copyFileSync(
  path.join(nm, "chart.js", "dist", "chart.umd.js"),
  path.join(sortie, "chart.umd.js")
);

const familles = [
  { paquet: "inter", fichier: "inter", poids: [400, 500, 600, 700], famille: "Inter" },
  { paquet: "plus-jakarta-sans", fichier: "plus-jakarta-sans", poids: [400, 500, 600, 700, 800], famille: "Plus Jakarta Sans" },
  { paquet: "jetbrains-mono", fichier: "jetbrains-mono", poids: [400, 500, 600], famille: "JetBrains Mono" },
  { paquet: "material-symbols-outlined", fichier: "material-symbols-outlined", poids: [400], famille: "Material Symbols Outlined" },
];

let css = "";
for (const f of familles) {
  for (const p of f.poids) {
    const nom = `${f.fichier}-latin-${p}-normal.woff2`;
    fs.copyFileSync(path.join(nm, "@fontsource", f.paquet, "files", nom), path.join(polices, nom));
    css += `@font-face{font-family:'${f.famille}';font-style:normal;font-display:swap;font-weight:${p};src:url(polices/${nom}) format('woff2');}\n`;
  }
}
css += ".material-symbols-outlined{font-family:'Material Symbols Outlined';font-weight:normal;font-style:normal;font-size:24px;line-height:1;letter-spacing:normal;text-transform:none;display:inline-block;white-space:nowrap;word-wrap:normal;direction:ltr;font-feature-settings:'liga';-webkit-font-smoothing:antialiased;}\n";
css += ".font-mono-num,.font-mono-numbers{font-family:'JetBrains Mono',monospace;}\n";
fs.writeFileSync(path.join(sortie, "polices.css"), css);

const commande = (fichier) =>
  `npx tailwindcss -c tailwind.config.js -i assets/tailwind.css -o "${path.join(sortie, fichier)}" --minify`;
execSync(commande("tailwind-forms.css"), { cwd: racine, stdio: "inherit", env: { ...process.env, AVEC_FORMULAIRES: "1" } });
execSync(commande("tailwind-base.css"), { cwd: racine, stdio: "inherit", env: { ...process.env, AVEC_FORMULAIRES: "0" } });
console.log("Ressources locales generees dans " + sortie);