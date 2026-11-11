// PDF целиком: страницы по прокрутке (холст pdf.js и слой текста поверх рисуются только рядом с видимой областью,
// дальние освобождают холст — память не растёт с каждой страницей). Открывается на странице цитаты, цитата
// подсвечена. Номер страницы, переход, «на весь экран». Модуль грузится лениво.

import { Button } from "@heroui/react";
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, TextLayer } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authHeaders } from "../../api/auth";
import { markRange, scrollWithin } from "./mark";
import { findQuote } from "./quote";

GlobalWorkerOptions.workerSrc = workerUrl;
const ORIGINAL_KEY = "amemo.pdf_original";

const docs = new Map<string, Promise<PDFDocumentProxy>>();
const open = (url: string) => {
  let p = docs.get(url);
  if (!p) {
    // pdf.js 6 не генерирует код во время выполнения — строгая CSP службы ему не мешает (e2e «csp»)
    p = getDocument({ url, rangeChunkSize: 65536, httpHeaders: authHeaders() }).promise;
    p.catch(() => docs.delete(url));
    docs.set(url, p);
  }
  return p;
};

/** Сколько страниц вокруг видимой держать нарисованными; дальше — только место под страницу. */
const KEEP = 1600;

type Mark = (found: HTMLElement | null) => void;

/** Одна страница: место нужной высоты сразу, холст и слой текста — когда страница рядом с видимой областью. */
function Sheet({
  doc,
  n,
  scale,
  est,
  root,
  quotes,
  onMarked,
}: {
  doc: PDFDocumentProxy;
  n: number;
  scale: number;
  est: { w: number; h: number };
  root: HTMLElement | null;
  quotes: string[];
  onMarked?: Mark;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  const [size, setSize] = useState(est);
  const live = useRef({ quotes, onMarked });
  live.current = { quotes, onMarked };

  useEffect(() => {
    const el = host.current;
    if (!el || !root) return;
    const io = new IntersectionObserver((es) => setNear(es.some((e) => e.isIntersecting)), {
      root,
      rootMargin: `${KEEP}px 0px`,
    });
    io.observe(el);
    return () => io.disconnect();
  }, [root]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    if (!near) {
      el.replaceChildren();
      return;
    }
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    (async () => {
      const p = await doc.getPage(n);
      const viewport = p.getViewport({ scale });
      if (cancelled) return;
      setSize({ w: viewport.width, h: viewport.height });
      const content = await p.getTextContent();
      if (cancelled) return;
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
      inner.append(canvas, layer);
      el.replaceChildren(inner);
      const render = p.render({
        canvas,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      task = render;
      const text = new TextLayer({ textContentSource: content, container: layer, viewport });
      await Promise.all([render.promise, text.render()]);
      if (cancelled) return;
      const { quotes: qs, onMarked: done } = live.current;
      if (!done) return;
      const els = text.textDivs as HTMLElement[];
      const strs = els.map((e) => e.textContent ?? "");
      let first: HTMLElement | null = null;
      for (const q of qs) {
        const r = findQuote(strs, q);
        if (r) first ??= markRange(els, r.start, r.end);
      }
      done(first);
    })().catch((e: unknown) => {
      if (cancelled || (e as { name?: string })?.name === "RenderingCancelledException") return;
      live.current.onMarked?.(null);
    });
    return () => {
      cancelled = true;
      task?.cancel();
      // далеко от видимой области холст освобождается, место под страницу остаётся
      el.replaceChildren();
    };
  }, [near, doc, n, scale]);

  return (
    <div
      ref={host}
      className="pdf__sheet"
      data-page={n}
      style={{ width: `${size.w}px`, height: `${size.h}px` }}
    />
  );
}

export default function PdfPage({
  url,
  page,
  quotes,
  onSelectText,
}: {
  url: string;
  /** Страница цитаты: с неё документ открывается. */
  page: number;
  quotes: string[];
  /** Выделение в слое текста — цитата для «+ Источник». */
  onSelectText?: (text: string) => void;
}) {
  const { t } = useTranslation();
  const view = useRef<HTMLElement>(null);
  const [root, setRoot] = useState<HTMLElement | null>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [base, setBase] = useState<{ w: number; h: number } | null>(null);
  const [width, setWidth] = useState(0);
  const [state, setState] = useState<"loading" | "ok" | "missing" | "error">("loading");
  const [zoom, setZoom] = useState(false);
  const [full, setFull] = useState(false);
  const [current, setCurrent] = useState(page);
  const [goto, setGoto] = useState("");
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
    let alive = true;
    setState("loading");
    setDoc(null);
    open(url)
      .then(async (d) => {
        const v = (await d.getPage(1)).getViewport({ scale: 1 });
        if (!alive) return;
        setBase({ w: v.width, h: v.height });
        setDoc(d);
      })
      .catch(() => alive && setState("error"));
    return () => {
      alive = false;
    };
  }, [url]);

  // ширина панели — под неё масштаб страницы
  useEffect(() => {
    const el = view.current;
    if (!el) return;
    setRoot(el);
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const pages = doc?.numPages ?? 0;
  const target = Math.min(Math.max(page, 1), Math.max(pages, 1));
  const fit = base && width ? Math.max(0.2, (width - 16) / base.w) : 1;
  const scale = zoom ? fit * 1.5 : fit;
  const est = base ? { w: base.w * scale, h: base.h * scale } : { w: 0, h: 0 };

  const toPage = useCallback((n: number) => {
    const el = view.current?.querySelector<HTMLElement>(`[data-page="${n}"]`);
    if (el && view.current) view.current.scrollTop = el.offsetTop - 8;
  }, []);
  // открываем на странице цитаты
  // biome-ignore lint/correctness/useExhaustiveDependencies: один раз на документ и страницу цитаты
  useEffect(() => {
    if (doc && base) requestAnimationFrame(() => toPage(target));
  }, [doc, base, target]);

  const onMarked = useCallback(
    (found: HTMLElement | null) => {
      setState(quotes.length && !found ? "missing" : "ok");
      scrollWithin(found);
      if (zoom && found && view.current)
        view.current.scrollLeft +=
          found.getBoundingClientRect().left - view.current.getBoundingClientRect().left - 24;
    },
    [quotes, zoom],
  );

  const onScroll = () => {
    const el = view.current;
    if (!el) return;
    const mid = el.scrollTop + el.clientHeight / 3;
    const sheets = el.querySelectorAll<HTMLElement>("[data-page]");
    let at = 1;
    for (const s of sheets) if (s.offsetTop <= mid) at = Number(s.dataset.page);
    // долистали до конца — последняя страница, даже если она не дошла до линии
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 2) at = sheets.length || at;
    setCurrent(at);
  };

  const onGoto = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    const n = Number(goto);
    if (Number.isInteger(n) && n >= 1 && n <= pages) {
      toPage(n);
      setCurrent(n);
    }
    setGoto("");
  };

  useEffect(() => {
    if (!full) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  return (
    <div className="pdf" data-original={original || undefined} data-full={full || undefined}>
      {state === "missing" && <p className="pdf__note">{t("source.quote_missing")}</p>}
      {state === "error" && (
        <p className="pdf__note" role="alert">
          {t("source.no_preview")}
        </p>
      )}
      <div className="pdf__tools">
        {pages > 0 && (
          <span className="pdf__pages">
            <span aria-live="polite">{t("source.page_of", { n: current, total: pages })}</span>
            <input
              className="fld pdf__goto"
              inputMode="numeric"
              aria-label={t("source.goto_page")}
              placeholder={t("source.goto_ph")}
              value={goto}
              onChange={(e) => setGoto(e.target.value.replace(/\D/g, ""))}
              onKeyDown={onGoto}
            />
          </span>
        )}
        <span className="spacer" />
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
        <Button size="sm" variant="ghost" aria-pressed={full} onPress={() => setFull((f) => !f)}>
          {full ? t("source.full_exit") : t("source.full")}
        </Button>
      </div>
      <section
        ref={view}
        className="pdf__zoom pdf__doc"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: документ прокручивается — нужен фокус с клавиатуры
        tabIndex={0}
        aria-label={t("source.preview")}
        aria-busy={state === "loading"}
        onScroll={onScroll}
      >
        {/* biome-ignore lint/a11y/noStaticElementInteractions: выделение мышью в слое текста; с клавиатуры цитата вводится полем рядом */}
        <div
          className="pdf__page"
          onMouseUp={() => {
            const sel = window.getSelection()?.toString().replace(/\s+/g, " ").trim();
            if (sel && onSelectText) onSelectText(sel);
          }}
        >
          {doc &&
            base &&
            Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <Sheet
                key={`${n}-${scale}`}
                doc={doc}
                n={n}
                scale={scale}
                est={est}
                root={root}
                quotes={n === target ? quotes : []}
                onMarked={n === target ? onMarked : undefined}
              />
            ))}
        </div>
      </section>
    </div>
  );
}
