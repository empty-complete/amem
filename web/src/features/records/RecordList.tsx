import { Button } from "@heroui/react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useDrag } from "react-aria";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { allRecordRefs, q, type RecordFilter } from "../../api/queries";
import type { components } from "../../api/schema";
import { RECORD_MIME } from "../../app/shell/Folders";
import { KindChip } from "../../ui/KindChip";
import { pickText } from "../../ui/lang";
import { RegionState } from "../../ui/RegionState";
import { RelativeTime } from "../../ui/RelativeTime";
import { StatusText } from "../../ui/StatusText";
import { ExportForm } from "../bundles/ExportForm";
import { MoveDialog } from "../write/MoveDialog";
import { useMoveRecords } from "../write/move";
import { hasFilter, RecordFilters } from "./RecordFilters";
import "./records.css";

type Summary = components["schemas"]["RecordSummary"];
type Vocab = components["schemas"]["VocabEntry"][];

export function recordPath(ref: string) {
  return ref.startsWith("ent:")
    ? ({ to: "/entity/$ref", params: { ref } } as const)
    : ({ to: "/atom/$ref", params: { ref } } as const);
}

/** Подпись вида или класса словами, с заглавной буквы: в словарях ядра подписи строчные («факт»).
 * На языке интерфейса, иначе на другом (pickText); нет в словаре — код как есть. */
export function kindLabel(vocab: Vocab | undefined, code: string, lang: string) {
  const v = vocab?.find((x) => x.code === code);
  const text = pickText(v?.label, lang);
  return text ? text.charAt(0).toLocaleUpperCase(lang) + text.slice(1) : code;
}

/** Как выбрали строку: Shift — диапазон от прошлой, иначе — переключить одну. */
export type Pick = { range: boolean };

export function RecordRow({
  r,
  vocab,
  classes,
  selected,
  onPick,
}: {
  r: Summary;
  vocab?: Vocab;
  classes?: Vocab;
  /** Есть — строку можно выбрать: флажок, Ctrl/⌘-щелчок, Shift-щелчок. */
  selected?: boolean;
  onPick?: (p: Pick) => void;
}) {
  const { t, i18n } = useTranslation();
  // строку можно перетащить на папку слева (React Aria: мышь, касание, клавиатура и чтецы)
  const { dragProps, isDragging } = useDrag({
    getItems: () => [{ [RECORD_MIME]: r.ref, "text/plain": r.label }],
  });
  return (
    <li {...dragProps} data-dragging={isDragging || undefined} data-selected={selected || undefined}>
      {onPick && (
        <input
          type="checkbox"
          className="row__chk"
          aria-label={t("select.one", { what: r.label })}
          checked={!!selected}
          onChange={() => {}}
          onClick={(e) => onPick({ range: e.shiftKey })}
        />
      )}
      <Link
        className="row"
        {...recordPath(r.ref)}
        onClick={(e) => {
          // Ctrl/⌘ и Shift выбирают строку, а не открывают запись
          if (!onPick || !(e.ctrlKey || e.metaKey || e.shiftKey)) return;
          e.preventDefault();
          onPick({ range: e.shiftKey });
        }}
      >
        <span className="main">
          <span className="line1">
            <KindChip
              kind={r.kind_or_class}
              target={r.target}
              label={kindLabel(r.target === "entity" ? classes : vocab, r.kind_or_class, i18n.language)}
            />
            <span className="ttl">{r.label}</span>
          </span>
          <span className="line2">
            {r.about?.map((a) => (
              <span key={a.ref}>{a.label}</span>
            ))}
            {r.folder && <span>{r.folder}</span>}
          </span>
        </span>
        <span className="side">
          <StatusText status={r.status} />
          <RelativeTime at={r.recorded_at} />
        </span>
      </Link>
    </li>
  );
}

/** «Все записи» или содержимое папки; папка — scope.folder записи. Страницы догружаются при прокрутке к концу. */
export function RecordList({
  folder,
  title,
  filter = {},
  onFilter,
}: {
  folder: string | null;
  title: string;
  filter?: RecordFilter;
  /** Есть — над списком строка фильтров; значения хранит адрес страницы. */
  onFilter?: (f: RecordFilter) => void;
}) {
  const { t } = useTranslation();
  const list = useInfiniteQuery(q.recordPages(folder, filter));
  const vocab = useQuery(q.vocab("kind"));
  const classes = useQuery(q.vocab("entity_class"));
  const end = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;
  useEffect(() => {
    const el = end.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (es) => {
        if (es.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "600px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? items.length;

  // выбор: набор ссылок или «все отобранные» (все записи под фильтром, не только загруженные)
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const anchor = useRef<number | null>(null);
  const [moving, setMoving] = useState(false);
  const [exporting, setExporting] = useState<string[] | null>(null);
  const moveMany = useMoveRecords();
  const scope = JSON.stringify([folder, filter]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: другой набор — выбор сбрасывается
  useEffect(() => {
    setSel(new Set());
    setAll(false);
    anchor.current = null;
  }, [scope]);
  const clear = () => {
    setSel(new Set());
    setAll(false);
  };
  const pick = (i: number, p: Pick) => {
    const ref = items[i]?.ref;
    if (!ref) return;
    setAll(false);
    setSel((prev) => {
      const next = new Set(prev);
      if (p.range && anchor.current != null) {
        const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)];
        for (const r of items.slice(a, b + 1)) next.add(r.ref);
      } else if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
    anchor.current = i;
  };
  const chosen = all ? total : sel.size;
  const refs = () => (all ? allRecordRefs(folder, filter) : Promise.resolve([...sel]));
  return (
    <section aria-labelledby="records-title">
      <div className="page-head">
        <h1 id="records-title">{title}</h1>
        {list.data && <span className="count">{t("records.count", { count: total })}</span>}
      </div>
      {onFilter && <RecordFilters value={filter} onChange={onFilter} />}
      {onFilter && chosen > 0 && (
        <div className="selbar" role="toolbar" aria-label={t("select.bar")}>
          <span className="selbar__n" aria-live="polite">
            {all ? t("select.all_on", { count: total }) : t("select.count", { count: chosen })}
          </span>
          {!all && chosen < total && (
            <button type="button" className="chipbtn" onClick={() => setAll(true)}>
              {t("select.all", { count: total })}
            </button>
          )}
          <span className="spacer" />
          <Button size="sm" variant="outline" onPress={() => setMoving(true)}>
            {t("select.move")}
          </Button>
          <Button size="sm" variant="outline" onPress={() => void refs().then(setExporting)}>
            {t("select.export")}
          </Button>
          <Button size="sm" variant="ghost" onPress={clear}>
            {t("select.clear")}
          </Button>
        </div>
      )}
      {list.isPending ? (
        <RegionState state="loading" />
      ) : list.isError ? (
        <RegionState
          state="error"
          message={errorText(list.error, t("region.offline"))}
          retry={() => list.refetch()}
        />
      ) : items.length === 0 ? (
        <RegionState state="empty" text={hasFilter(filter) ? t("filters.empty") : t("records.empty")} />
      ) : (
        <>
          <ul className="rows">
            {items.map((r, i) => (
              <RecordRow
                key={r.ref}
                r={r}
                vocab={vocab.data}
                classes={classes.data}
                selected={onFilter ? all || sel.has(r.ref) : undefined}
                onPick={onFilter ? (p) => pick(i, p) : undefined}
              />
            ))}
          </ul>
          {hasNextPage && (
            <div ref={end} className="rows__more">
              <Button variant="outline" isPending={isFetchingNextPage} onPress={() => void fetchNextPage()}>
                {isFetchingNextPage ? t("records.loading_more") : t("records.more")}
              </Button>
            </div>
          )}
        </>
      )}
      <MoveDialog
        current={null}
        open={moving}
        onClose={() => setMoving(false)}
        onMove={(to, name) => {
          moveMany(
            all ? () => allRecordRefs(folder, filter) : [...sel],
            to,
            t("folders.moved_many", {
              count: chosen,
              to: name,
            }),
          );
          clear();
        }}
      />
      <ModalOverlay
        isOpen={exporting != null}
        onOpenChange={(o) => !o && setExporting(null)}
        isDismissable
        className="modal-overlay"
      >
        <Modal className="modal modal--wide">
          <Dialog className="modal__in" aria-label={t("bundles.dialog")}>
            <Heading slot="title">{t("bundles.dialog")}</Heading>
            {exporting && <ExportForm refs={exporting} />}
          </Dialog>
        </Modal>
      </ModalOverlay>
    </section>
  );
}
