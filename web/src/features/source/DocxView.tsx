// DOCX с вёрсткой (заголовки, таблицы, рисунки) — docx-preview, лениво. Цитата подсвечена и прокручена в вид.
// Не отрисовалось — показывает запасной вид (извлечённый текст), как раньше.
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api/auth";
import { RegionState } from "../../ui/RegionState";
import { markQuote } from "./mark";

export { markQuote };

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
