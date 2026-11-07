import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { components } from "../../api/schema";
import { agentName } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { RelativeTime } from "../../ui/RelativeTime";
import { REASON_ICON } from "./reasons";

type Item = components["schemas"]["ReviewItem"];
const ROW = 68;
const VIRTUAL_FROM = 60;

/** Список пунктов (виртуальный: тысяча пунктов листается без рывков). */
export function QueueList({
  items,
  selected,
  onSelect,
}: {
  items: Item[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  // короткую очередь рисуем целиком (проще для чтецов), длинную — виртуально: тысяча пунктов без рывков
  const virtual = items.length > VIRTUAL_FROM;
  const v = useVirtualizer({
    count: virtual ? items.length : 0,
    getScrollElement: () => box.current,
    estimateSize: () => ROW,
    overscan: 8,
  });
  const idx = items.findIndex((i) => i.id === selected);
  useEffect(() => {
    if (virtual && idx >= 0) v.scrollToIndex(idx, { align: "auto" });
    else box.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [idx, v, virtual]);
  const rows = virtual
    ? v.getVirtualItems().map((r) => ({ index: r.index, start: r.start }))
    : items.map((_, index) => ({ index, start: index * ROW }));
  return (
    <div ref={box} className="queue" role="listbox" aria-label={t("review.list")}>
      <div style={{ height: virtual ? v.getTotalSize() : items.length * ROW, position: "relative" }}>
        {rows.map((row) => {
          const it = items[row.index] as Item;
          return (
            <div
              key={it.id}
              role="option"
              aria-selected={it.id === selected}
              tabIndex={it.id === selected || (idx < 0 && row.index === 0) ? 0 : -1}
              className="qrow"
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                transform: `translateY(${row.start}px)`,
                height: ROW,
              }}
              onClick={() => onSelect(it.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(it.id);
                }
              }}
            >
              <span className="qrow__ttl">{it.label ?? it.ref}</span>
              <span className="qrow__meta">
                <span className="qrow__reason">
                  <Icon name={REASON_ICON[it.reason]} size={12} />
                  {t(`review.r.${it.reason}`)}
                </span>
                <span>{agentName(it.author ?? it.created_by, i18n.language)}</span>
                <RelativeTime at={it.created_at} />
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
