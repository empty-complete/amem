import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { agentName } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { type LangString, useText } from "../../ui/lang";
import { RelativeTime } from "../../ui/RelativeTime";
import type { Grouping, Item, Row } from "./groups";
import { REASON_ICON } from "./reasons";

const ROW = 84;
const HEAD = 36;
const VIRTUAL_FROM = 60;
const REF = /^(atm|ent):/;
const size = (r: Row | undefined) => (r?.kind === "head" ? HEAD : ROW);

/** О чём сомнение — первый кандидат пункта («Похожая запись: …»); подпись — из кеша, только у видимых строк. */
function Doubt({ it }: { it: Item }) {
  const { t } = useTranslation();
  const { text } = useText();
  const c = ((it.details ?? {}) as { candidates?: { code: string; ref: string }[] }).candidates?.[0];
  const rec = useQuery({ ...q.record(c?.ref ?? ""), enabled: !!c && REF.test(c.ref), staleTime: 60_000 });
  if (!c) return null;
  const label =
    text((rec.data?.payload as { label?: LangString } | undefined)?.label) || (REF.test(c.ref) ? "…" : c.ref);
  return (
    <span className="qrow__doubt">
      {t(`review.code.${c.code}`, { defaultValue: c.code })}: {label}
    </span>
  );
}

/** Список пунктов: по времени или по документам с заголовками групп; длинный — виртуальный. */
export function QueueList({
  rows,
  grouping,
  selected,
  onSelect,
}: {
  rows: Row[];
  grouping: Grouping;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  // короткую очередь рисуем целиком (проще для чтецов), длинную — виртуально
  const virtual = rows.length > VIRTUAL_FROM;
  const v = useVirtualizer({
    count: virtual ? rows.length : 0,
    getScrollElement: () => box.current,
    estimateSize: (i) => size(rows[i]),
    overscan: 8,
  });
  const idx = rows.findIndex((r) => r.kind === "item" && r.item.id === selected);
  const firstItem = rows.findIndex((r) => r.kind === "item");
  useEffect(() => {
    if (virtual && idx >= 0) v.scrollToIndex(idx, { align: "auto" });
    else box.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [idx, v, virtual]);
  const starts = useMemo(() => {
    let y = 0;
    return rows.map((r) => {
      const s = y;
      y += size(r);
      return s;
    });
  }, [rows]);
  const total = (starts.at(-1) ?? 0) + size(rows.at(-1));
  const shown = virtual
    ? v.getVirtualItems().map((r) => ({ index: r.index, start: r.start }))
    : rows.map((_, index) => ({ index, start: starts[index] ?? 0 }));
  return (
    <div ref={box} className="queue" role="listbox" aria-label={t("review.list")}>
      <div style={{ height: virtual ? v.getTotalSize() : total, position: "relative" }}>
        {shown.map(({ index, start }) => {
          const r = rows[index] as Row;
          const place = {
            position: "absolute" as const,
            top: 0,
            left: 0,
            right: 0,
            transform: `translateY(${start}px)`,
            height: size(r),
          };
          if (r.kind === "head")
            return (
              <div key={`h-${r.key}`} role="presentation" className="qhead" style={place}>
                <span className="qhead__name">{r.name}</span>
                <span className="count">{r.count}</span>
              </div>
            );
          const it = r.item;
          return (
            <div
              key={it.id}
              role="option"
              aria-selected={it.id === selected}
              tabIndex={it.id === selected || (idx < 0 && index === firstItem) ? 0 : -1}
              className="qrow"
              style={place}
              onClick={() => onSelect(it.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(it.id);
                }
              }}
            >
              <span className="qrow__ttl">{it.label ?? it.ref}</span>
              <Doubt it={it} />
              <span className="qrow__meta">
                <span className="qrow__reason">
                  <Icon name={REASON_ICON[it.reason]} size={12} />
                  {t(`review.r.${it.reason}`)}
                </span>
                {grouping === "time" && it.source?.object_name ? (
                  <span className="qrow__doc">{it.source.object_name}</span>
                ) : (
                  <span>{agentName(it.author ?? it.created_by, i18n.language)}</span>
                )}
                <RelativeTime at={it.created_at} />
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
