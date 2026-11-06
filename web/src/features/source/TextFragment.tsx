import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { markRange } from "./mark";
import { findQuote } from "./quote";

/** Текст версии (страница или весь) абзацами, цитата подсвечена тем же поиском, что и на PDF. */
export function TextFragment({
  id,
  version,
  page,
  quotes,
}: {
  id: string;
  version: number;
  page?: number;
  quotes: string[];
}) {
  const { t } = useTranslation();
  const text = useQuery(q.objectText(id, version, page));
  const box = useRef<HTMLDivElement>(null);
  const paras = useMemo(
    () => (text.data?.pages ?? []).flatMap((p) => p.split(/\n+/)).filter(Boolean),
    [text.data],
  );

  useEffect(() => {
    const els = [...(box.current?.querySelectorAll<HTMLElement>("p") ?? [])];
    if (!els.length) return;
    els.forEach((el, i) => {
      el.textContent = paras[i] ?? "";
    });
    let first: HTMLElement | null = null;
    for (const quote of quotes) {
      const r = findQuote(paras, quote);
      if (r) first ??= markRange(els, r.start, r.end);
    }
    first?.scrollIntoView?.({ block: "center" });
  }, [paras, quotes]);

  if (text.isPending) return <RegionState state="loading" />;
  if (text.isError) return <RegionState state="error" message={errorText(text.error, t("region.offline"))} />;
  return (
    <div ref={box} className="textfrag">
      {paras.map((p, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: абзацы версии неизменны, порядок и есть ключ
        <p key={i}>{p}</p>
      ))}
    </div>
  );
}
