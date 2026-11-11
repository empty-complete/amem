// DOCX с вёрсткой (заголовки, таблицы, рисунки) — docx-preview, лениво. Цитата подсвечена и прокручена в вид.
// Не отрисовалось — показывает запасной вид (извлечённый текст), как раньше.
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api/auth";
import { RegionState } from "../../ui/RegionState";

const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

/** Подсветить первое вхождение начала цитаты в одном текстовом узле (абзацы docx-preview — узлы целиком). */
export function markQuote(root: HTMLElement, quote: string): HTMLElement | null {
  const want = norm(quote).slice(0, 60);
  if (!want) return null;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const text = n.textContent ?? "";
    const at = norm(text).indexOf(want);
    if (at < 0) continue;
    // позиция в исходном тексте: нормализация сжимает пробелы — ищем по словам с начала цитаты
    const words = want.split(" ");
    const re = new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"), "i");
    const m = text.match(re);
    if (!m || m.index == null) continue;
    const range = document.createRange();
    range.setStart(n, m.index);
    range.setEnd(n, m.index + m[0].length);
    const mark = document.createElement("mark");
    mark.className = "docx__quote";
    range.surroundContents(mark);
    return mark;
  }
  return null;
}

export default function DocxView({
  url,
  quotes,
  fallback,
}: {
  url: string;
  quotes: string[];
  /** Что показать, если файл не отрисовался: извлечённый текст. */
  fallback: ReactNode;
}) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ok" | "failed">("loading");
  const key = quotes.join("\n");
  // biome-ignore lint/correctness/useExhaustiveDependencies: quotes — по содержимому (key)
  useEffect(() => {
    let alive = true;
    setState("loading");
    (async () => {
      try {
        const [{ renderAsync }, res] = await Promise.all([import("docx-preview"), apiFetch(url)]);
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        if (!alive || !box.current) return;
        box.current.replaceChildren();
        await renderAsync(blob, box.current, undefined, {
          className: "docx",
          inWrapper: false,
          ignoreWidth: true,
          ignoreHeight: true,
          breakPages: false,
          experimental: false,
        });
        if (!alive || !box.current) return;
        setState("ok");
        const first = quotes.map((q) => (box.current ? markQuote(box.current, q) : null)).find(Boolean);
        first?.scrollIntoView({ block: "center" });
      } catch {
        if (alive) setState("failed");
      }
    })();
    return () => {
      alive = false;
    };
  }, [url, key]);
  if (state === "failed") return <>{fallback}</>;
  return (
    <div className="docxview">
      {state === "loading" && <RegionState state="loading" />}
      <div ref={box} className="docxview__doc" aria-label={t("source.docx")} role="document" />
    </div>
  );
}
