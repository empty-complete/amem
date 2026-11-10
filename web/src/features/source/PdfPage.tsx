// Страница PDF с подсветкой цитаты: холст pdf.js и слой текста поверх. Модуль грузится лениво.

import { Button } from "@heroui/react";
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, TextLayer } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { markRange, scrollWithin } from "./mark";
import { findQuote } from "./quote";

GlobalWorkerOptions.workerSrc = workerUrl;
const ORIGINAL_KEY = "amemo.pdf_original";

type TextItem = { str: string; transform: number[]; width: number; height: number };

/** Рамка текста страницы (в точках, от верхнего левого угла) с полем; без текста — вся страница. */
function textBox(items: TextItem[], pw: number, ph: number) {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const it of items) {
    // пустые и одиночные номера страниц не раздвигают рамку
    if (!it.str?.trim() || /^\d{1,4}$/.test(it.str.trim())) continue;
    const [, , , , e = 0, f = 0] = it.transform;
    xs.push(e, e + it.width);
    ys.push(ph - f - it.height, ph - f);
  }
  if (!xs.length) return { x: 0, y: 0, w: pw, h: ph };
  const pad = 18;
  const x = Math.max(0, Math.min(...xs) - pad);
  const y = Math.max(0, Math.min(...ys) - pad);
  return { x, y, w: Math.min(pw, Math.max(...xs) + pad) - x, h: Math.min(ph, Math.max(...ys) + pad) - y };
}

const docs = new Map<string, Promise<PDFDocumentProxy>>();
const open = (url: string) => {
  let p = docs.get(url);
  if (!p) {
    // pdf.js 6 не генерирует код во время выполнения — строгая CSP службы ему не мешает (e2e «csp»)
    p = getDocument({ url, rangeChunkSize: 65536 }).promise;
    p.catch(() => docs.delete(url));
    docs.set(url, p);
  }
  return p;
};

export default function PdfPage({
  url,
  page,
  quotes,
  onSelectText,
}: {
  url: string;
  page: number;
  quotes: string[];
  /** Выделение в слое текста — цитата для «+ Источник». */
  onSelectText?: (text: string) => void;
}) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ok" | "missing" | "error">("loading");

  const [zoom, setZoom] = useState(false);
  // «Как в файле» — выбор человека, запоминается: по умолчанию в тёмной теме страница перекрашена под палитру
  // (как в читалках); кнопка видна только в тёмной теме (source.css)
  const [original, setOriginal] = useState(() => {
    try {
      return window.localStorage.getItem(ORIGINAL_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggleOriginal = () =>
    setOriginal((o) => {
      try {
        window.localStorage.setItem(ORIGINAL_KEY, o ? "0" : "1");
      } catch {}
      return !o;
    });

  useEffect(() => {
    const host = box.current;
    if (!host) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    setState("loading");
    (async () => {
      const doc = await open(url);
      const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
      const content = await p.getTextContent();
      if (cancelled) return;
      const base = p.getViewport({ scale: 1 });
      // поля страницы обрезаем по тексту: в узкой панели строки становятся крупнее
      const box_ = textBox(content.items as TextItem[], base.width, base.height);
      const width = host.clientWidth || 360;
      const sizes = (content.items as TextItem[])
        .map((i) => i.height)
        .filter((h) => h > 0)
        .sort((a, b) => a - b);
      const median = sizes[Math.floor(sizes.length / 2)] ?? 11;
      // не мельче 10 px на экране; «Крупнее» — ещё в полтора раза, с прокруткой вбок
      const fit = Math.max(width / box_.w, 10 / median);
      const scale = zoom ? fit * 1.5 : fit;
      const viewport = p.getViewport({ scale });
      const ratio = globalThis.devicePixelRatio || 1;
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const layer = document.createElement("div");
      layer.className = "textLayer";
      layer.style.setProperty("--scale-factor", String(scale));
      layer.style.setProperty("--total-scale-factor", String(scale));
      const inner = document.createElement("div");
      inner.className = "pdf__inner";
      inner.style.width = `${viewport.width}px`;
      inner.style.height = `${viewport.height}px`;
      inner.style.left = `${-box_.x * scale}px`;
      inner.style.top = `${-box_.y * scale}px`;
      inner.append(canvas, layer);
      const sheet = document.createElement("div");
      sheet.className = "pdf__sheet";
      sheet.style.width = `${box_.w * scale}px`;
      sheet.style.height = `${box_.h * scale}px`;
      sheet.append(inner);
      host.replaceChildren(sheet);
      const render = p.render({
        canvas,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      task = render;
      const text = new TextLayer({ textContentSource: content, container: layer, viewport });
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
      scrollWithin(first);
      if (zoom && first) {
        const view = host.closest<HTMLElement>(".pdf__zoom");
        if (view)
          view.scrollLeft += first.getBoundingClientRect().left - view.getBoundingClientRect().left - 24;
      }
    })().catch((e: unknown) => {
      if (cancelled || (e as { name?: string })?.name === "RenderingCancelledException") return;
      setState("error");
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [url, page, quotes, zoom]);

  return (
    <div className="pdf" data-original={original || undefined}>
      {state === "missing" && <p className="pdf__note">{t("source.quote_missing")}</p>}
      {state === "error" && (
        <p className="pdf__note" role="alert">
          {t("source.no_preview")}
        </p>
      )}
      <div className="pdf__tools">
        <Button
          size="sm"
          variant="ghost"
          className="pdf__darkbtn"
          aria-pressed={original}
          onPress={toggleOriginal}
        >
          {t("source.original_colors")}
        </Button>
        <Button size="sm" variant="ghost" aria-pressed={zoom} onPress={() => setZoom((z) => !z)}>
          {zoom ? t("source.zoom_fit") : t("source.zoom_in")}
        </Button>
      </div>
      <section
        className="pdf__zoom"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: страница шире панели и прокручивается — нужен фокус с клавиатуры
        tabIndex={0}
        aria-label={t("source.preview")}
        aria-busy={state === "loading"}
      >
        {/* biome-ignore lint/a11y/noStaticElementInteractions: выделение мышью в слое текста; с клавиатуры цитата вводится полем рядом */}
        <div
          ref={box}
          className="pdf__page"
          onMouseUp={() => {
            const sel = window.getSelection()?.toString().replace(/\s+/g, " ").trim();
            if (sel && onSelectText) onSelectText(sel);
          }}
        />
      </section>
    </div>
  );
}
