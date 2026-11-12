// Просмотр файлов-источников без своей вёрстки: Markdown — отрисованным, презентация — слайдами (текст слайда).
// Выделение мышью — цитата для «+ Источник».
import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { renderMarkdown } from "../record/markdown";
import { markQuote, scrollWithin } from "./mark";
import { TextFragment } from "./TextFragment";

/** Выделенный мышью текст внутри — цитатой (пробелы сжаты); с клавиатуры цитату вводят полем рядом. */
export function SelectQuote({
  onQuote,
  children,
}: {
  onQuote?: (text: string) => void;
  children: ReactNode;
}) {
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: выделение мышью; с клавиатуры цитата вводится полем рядом
    <div
      onMouseUp={() => {
        const text = window.getSelection()?.toString().replace(/\s+/g, " ").trim();
        if (text && onQuote) onQuote(text);
      }}
    >
      {children}
    </div>
  );
}

/** Файл Markdown — отрисованным, как тело записи (без HTML, формулы KaTeX); цитата подсвечена. */
export function MarkdownView({ id, version, quotes }: { id: string; version: number; quotes: string[] }) {
  const { t } = useTranslation();
  const text = useQuery(q.objectText(id, version));
  const box = useRef<HTMLDivElement>(null);
  const src = (text.data?.pages ?? []).join("\n\n");
  const key = quotes.join("\n");
  // biome-ignore lint/correctness/useExhaustiveDependencies: quotes — по содержимому (key)
  useEffect(() => {
    let live = true;
    // [[ссылки]] файла — просто текст: это не записи базы
    renderMarkdown(src, () => "#").then((frag) => {
      if (!live || !box.current) return;
      box.current.replaceChildren(frag);
      const first = quotes.map((x) => (box.current ? markQuote(box.current, x) : null)).find(Boolean);
      scrollWithin(first ?? null);
    });
    return () => {
      live = false;
    };
  }, [src, key]);
  if (text.isPending) return <RegionState state="loading" />;
  if (text.isError) return <RegionState state="error" message={errorText(text.error, t("region.offline"))} />;
  if (!src.trim()) return <p className="muted">{t("source.no_preview")}</p>;
  return <div ref={box} className="prose mdfile" />;
}

/** Презентация — по слайду: стрелки листают, текст слайда абзацами; выделение — цитата. */
export function SlidesView({
  id,
  version,
  slide,
  onSlide,
  quotes,
  onSelectText,
}: {
  id: string;
  version: number;
  slide: number;
  onSlide: (n: number) => void;
  quotes: string[];
  onSelectText?: (text: string) => void;
}) {
  const { t } = useTranslation();
  const all = useQuery(q.objectText(id, version));
  const count = all.data?.pages.length ?? 0;
  if (all.isPending) return <RegionState state="loading" />;
  if (all.isError) return <RegionState state="error" message={errorText(all.error, t("region.offline"))} />;
  if (!count) return <p className="muted">{t("source.no_slides")}</p>;
  const n = Math.min(Math.max(1, slide), count);
  return (
    <div className="slides">
      <div className="pick__row">
        <Button
          size="sm"
          variant="ghost"
          isDisabled={n <= 1}
          onPress={() => onSlide(n - 1)}
          aria-label={t("pick.prev")}
        >
          ←
        </Button>
        <span>{t("source.slide_of", { n, count })}</span>
        <Button
          size="sm"
          variant="ghost"
          isDisabled={n >= count}
          onPress={() => onSlide(n + 1)}
          aria-label={t("pick.next")}
        >
          →
        </Button>
      </div>
      <div className="slides__card">
        <TextFragment
          id={id}
          version={version}
          page={n}
          quotes={quotes}
          onSelectText={onSelectText ? (s) => onSelectText(s) : undefined}
        />
      </div>
    </div>
  );
}
