import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { QueueList } from "./QueueList";
import { ReviewItemPane } from "./ReviewItem";
import { REASONS } from "./reasons";
import { type Outcome, useDecision, usePendingDecisions } from "./useDecision";
import "../record/record.css";
import "../write/write.css";
import "./review.css";

function inField(el: Element | null) {
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || (el as HTMLElement).isContentEditable);
}

/** Проверка (разд. 5.7): очередь слева, пункт справа, решение внизу; клавиши J K Y N S. */
export function ReviewPage({
  itemId,
  reason,
  state = "open",
}: {
  itemId?: string;
  reason?: string;
  state?: "open" | "done";
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const list = useQuery(q.reviewItems({ state, reason }));
  const pending = usePendingDecisions();
  const [note, setNote] = useState("");
  const [already, setAlready] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const items = useMemo(() => (list.data ?? []).filter((i) => !pending.has(i.id)), [list.data, pending]);
  const ordered = useMemo(
    () => [...items.filter((i) => !skipped.has(i.id)), ...items.filter((i) => skipped.has(i.id))],
    [items, skipped],
  );
  const current = ordered.find((i) => i.id === itemId) ?? null;
  const go = useCallback(
    (id: string | null, replace = false) =>
      id
        ? navigate({
            to: "/review/$itemId",
            params: { itemId: id },
            search: { reason, state } as never,
            replace,
          })
        : navigate({ to: "/review", search: { reason, state } as never, replace }),
    [navigate, reason, state],
  );
  const onAlready = useCallback((who: string) => setAlready(t("review.already", { who })), [t]);
  const decide = useDecision(onAlready);

  // без выбранного пункта на широком экране открываем первый
  useEffect(() => {
    if (!itemId && ordered[0] && window.matchMedia?.("(min-width: 1100px)").matches) go(ordered[0].id, true);
  }, [itemId, ordered, go]);
  useEffect(() => setNote(""), [itemId]);

  const idx = current ? ordered.indexOf(current) : -1;
  const next = () => ordered[idx + 1]?.id ?? ordered[idx - 1]?.id ?? null;
  const act = (outcome: Outcome) => {
    if (!current || state === "done") return;
    setAlready(null);
    const n = next();
    decide(
      current.id,
      outcome,
      outcome === "confirmed" ? t("review.toast_confirmed") : t("review.toast_refuted"),
      note,
    );
    go(n);
  };
  const skip = () => {
    if (!current) return;
    setSkipped((s) => new Set(s).add(current.id));
    go(ordered[idx + 1]?.id ?? null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || inField(document.activeElement)) return;
      const k = e.code;
      if (k === "KeyJ" || k === "KeyK") {
        e.preventDefault();
        const to = ordered[idx + (k === "KeyJ" ? 1 : -1)] ?? (idx < 0 ? ordered[0] : null);
        if (to) go(to.id);
      } else if (k === "KeyY") {
        e.preventDefault();
        act("confirmed");
      } else if (k === "KeyN") {
        e.preventDefault();
        e.stopImmediatePropagation();
        act("refuted");
      } else if (k === "KeyS") {
        e.preventDefault();
        skip();
      }
    };
    // захват: «N» здесь — «Отклонить», а не «новая запись» оболочки
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const filters = (
    <div className="rfilters">
      <select
        className="fld"
        aria-label={t("review.reason")}
        value={reason ?? ""}
        onChange={(e) =>
          navigate({ to: "/review", search: { reason: e.target.value || undefined, state } as never })
        }
      >
        <option value="">{t("review.any")}</option>
        {REASONS.map((r) => (
          <option key={r} value={r}>
            {t(`review.r.${r}`)}
          </option>
        ))}
      </select>
      <div className="seg" role="radiogroup" aria-label={t("review.state")}>
        {(["open", "done"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={state === s}
            className="seg__opt"
            onClick={() =>
              navigate({ to: "/review", search: { reason, state: s === "open" ? undefined : s } as never })
            }
          >
            {t(`review.${s}`)}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="review" data-item={itemId ? true : undefined}>
      <section className="review__list" aria-labelledby="review-title">
        <h1 id="review-title" className="review__h">
          {t("review.title")}
          {list.data && <span className="count">{items.length}</span>}
        </h1>
        {filters}
        {list.isPending ? (
          <RegionState state="loading" />
        ) : list.isError ? (
          <RegionState
            state="error"
            message={errorText(list.error, t("region.offline"))}
            retry={() => list.refetch()}
          />
        ) : ordered.length === 0 ? (
          <RegionState state="empty" text={state === "done" ? t("review.empty_done") : t("review.empty")} />
        ) : (
          <QueueList items={ordered} selected={itemId ?? null} onSelect={(id) => go(id)} />
        )}
        <p className="muted review__keys">{t("review.keys")}</p>
      </section>
      <section className="review__item" aria-label={current?.label ?? t("review.pick")}>
        {/* строка статуса всегда на месте: сетка «статус · пункт · решение» не сдвигается */}
        <p className="pending review__status" role="status">
          {already}
        </p>
        {itemId ? (
          <>
            <div className="review__scroll">
              <ReviewItemPane key={itemId} id={itemId} onBack={() => go(null)} />
            </div>
            {state !== "done" && current && (
              <div className="decide" role="group" aria-label={t("review.title")}>
                <input
                  className="fld decide__note"
                  aria-label={t("review.note")}
                  placeholder={t("review.note_ph")}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <Button variant="ghost" onPress={skip} aria-label={t("review.skip_k")}>
                  {t("review.skip")}
                </Button>
                <Button variant="outline" onPress={() => act("refuted")} aria-label={t("review.refute_k")}>
                  {t("review.refute")}
                </Button>
                <Button
                  className="pillbtn"
                  onPress={() => act("confirmed")}
                  aria-label={t("review.confirm_k")}
                >
                  {t("review.confirm")}
                </Button>
              </div>
            )}
          </>
        ) : (
          ordered.length > 0 && <p className="muted review__pick">{t("review.pick")}</p>
        )}
      </section>
    </div>
  );
}
