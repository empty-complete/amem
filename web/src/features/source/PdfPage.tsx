// Страница PDF с подсветкой цитаты: холст pdf.js и слой текста поверх. Модуль грузится лениво.
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, TextLayer } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { markRange } from "./mark";
import { findQuote } from "./quote";

GlobalWorkerOptions.workerSrc = workerUrl;

const docs = new Map<string, Promise<PDFDocumentProxy>>();
const open = (url: string) => {
  let p = docs.get(url);
  if (!p) {
    p = getDocument({ url, rangeChunkSize: 65536 }).promise;
    p.catch(() => docs.delete(url));
    docs.set(url, p);
  }
  return p;
};

export default function PdfPage({ url, page, quotes }: { url: string; page: number; quotes: string[] }) {
  const { t } = useTranslation();
  const box = useRef<HTMLElement>(null);
  const [state, setState] = useState<"loading" | "ok" | "missing" | "error">("loading");

  useEffect(() => {
    const host = box.current;
    if (!host) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    setState("loading");
    (async () => {
      const doc = await open(url);
      const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
      if (cancelled) return;
      const width = host.clientWidth || 360;
      const base = p.getViewport({ scale: 1 });
      const viewport = p.getViewport({ scale: width / base.width });
      const ratio = globalThis.devicePixelRatio || 1;
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const layer = document.createElement("div");
      layer.className = "textLayer";
      layer.style.setProperty("--scale-factor", String(viewport.scale));
      layer.style.setProperty("--total-scale-factor", String(viewport.scale));
      const sheet = document.createElement("div");
      sheet.className = "pdf__sheet";
      sheet.style.width = `${viewport.width}px`;
      sheet.style.height = `${viewport.height}px`;
      sheet.append(canvas, layer);
      host.replaceChildren(sheet);
      const render = p.render({
        canvas,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      task = render;
      const text = new TextLayer({ textContentSource: p.streamTextContent(), container: layer, viewport });
      await Promise.all([render.promise, text.render()]);
      if (cancelled) return;
      const els = text.textDivs as HTMLElement[];
      const strs = els.map((e) => e.textContent ?? "");
      let first: HTMLElement | null = null;
      for (const q of quotes) {
        const r = findQuote(strs, q);
        if (r) first ??= markRange(els, r.start, r.end);
      }
      setState(quotes.length && !first ? "missing" : "ok");
      first?.scrollIntoView?.({ block: "center" });
    })().catch((e: unknown) => {
      if (cancelled || (e as { name?: string })?.name === "RenderingCancelledException") return;
      setState("error");
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [url, page, quotes]);

  return (
    <div className="pdf">
      {state === "missing" && <p className="pdf__note">{t("source.quote_missing")}</p>}
      {state === "error" && (
        <p className="pdf__note" role="alert">
          {t("source.no_preview")}
        </p>
      )}
      <section
        ref={box}
        className="pdf__page"
        aria-busy={state === "loading"}
        aria-label={t("source.preview")}
      />
    </div>
  );
}
