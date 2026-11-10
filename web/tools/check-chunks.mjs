// Проверка манифеста сборки: тяжёлые куски (граф, 3D, pdf.js, KaTeX, CodeMirror) не входят в первую загрузку.
// Обходит статические imports входа; динамические (lazy) — не в счёт.
import { readFileSync } from "node:fs";

const path = process.argv[2] ?? "python/amemo_web/dist/.vite/manifest.json";
const manifest = JSON.parse(readFileSync(path, "utf8"));
const LAZY =
  /SkyCanvas|Sky3D|PdfPage|SourceView|BodyEditor|KindDrawer|codemirror|katex|force-graph|3d-force-graph|three|pdfjs|codemirror/i;

const entries = Object.entries(manifest).filter(([, c]) => c.isEntry);
if (!entries.length) throw new Error("в манифесте нет входа");
const seen = new Set();
const walk = (key) => {
  if (seen.has(key)) return;
  seen.add(key);
  for (const k of manifest[key]?.imports ?? []) walk(k);
};
for (const [key] of entries) walk(key);
const bad = [...seen].filter((k) => LAZY.test(k) || LAZY.test(manifest[k]?.file ?? ""));
if (bad.length) {
  console.error(
    `В первую загрузку попали ленивые куски:\n${bad.map((k) => `  ${k} → ${manifest[k].file}`).join("\n")}`,
  );
  process.exit(1);
}
console.log(`Первая загрузка: ${seen.size} кусков, ленивых среди них нет.`);
