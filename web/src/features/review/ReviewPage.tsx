import { Button, ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q, REVIEW_LIMIT } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { arrange, facets, filterItems, type Grouping, nextAfter } from "./groups";
import { QueueList } from "./QueueList";
import { ReviewItemPane } from "./ReviewItem";
import { aboutEdit, forPerson, REASONS } from "./reasons";
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
  group,
  object,
  about,
  who,
}: {
  itemId?: string;
  reason?: string;
  state?: "open" | "done";
  group?: "source";
  object?: string;
  about?: string;
  /** Вкладка: без значения — «Ждут вас» (решает человек), model — «Разбирает модель» (смысловая проверка). */
  who?: "model";
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const list = useQuery(q.reviewItems({ state, reason }));
  const pending = usePendingDecisions();
  const [note, setNote] = useState("");
  const [already, setAlready] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const grouping: Grouping = group === "source" ? "source" : "time";
  const names = useMemo(() => ({ none: t("review.no_source"), entities: t("review.entities") }), [t]);
  const loaded = list.data ?? [];
  // ровно предел — значит, пункты есть и дальше: честная строка вместо молча обрезанной очереди
  const capped = loaded.length >= REVIEW_LIMIT;
  const live = useMemo(() => loaded.filter((i) => !pending.has(i.id)), [loaded, pending]);
  const mine = useMemo(() => live.filter((i) => forPerson(i.reason)), [live]);
  const all = useMemo(
    () => (who === "model" ? live.filter((i) => !forPerson(i.reason)) : mine),
    [live, mine, who],
  );
  const stats = useQuery({ ...q.reviewStats(7), enabled: state === "open" });
  const verifier = stats.data?.verifier;
  const facet = useMemo(() => facets(all, names), [all, names]);
  const items = useMemo(() => filterItems(all, { object, about }), [all, object, about]);
  const { ordered, rows } = useMemo(() => {
    // пропущенные — в конец, как раньше; группы и порядок — по выбору
    const rest = [...items.filter((i) => !skipped.has(i.id)), ...items.filter((i) => skipped.has(i.id))];
    return arrange(rest, grouping, names);
  }, [items, skipped, grouping, names]);
  const current = ordered.find((i) => i.id === itemId) ?? null;
  const go = useCallback(
    (id: string | null, replace = false) =>
      id
        ? navigate({
            to: "/review/$itemId",
            params: { itemId: id },
            search: { reason, state, group, object, about, who } as never,
            replace,
          })
        : navigate({ to: "/review", search: { reason, state, group, object, about, who } as never, replace }),
    [navigate, reason, state, group, object, about, who],
  );
  const onAlready = useCallback((who: string) => setAlready(t("review.already", { who })), [t]);
  const decide = useDecision(onAlready);

  // без выбранного пункта на широком экране открываем первый
  useEffect(() => {
    if (!itemId && ordered[0] && window.matchMedia?.("(min-width: 1100px)").matches) go(ordered[0].id, true);
  }, [itemId, ordered, go]);
  // другой пункт — чистая заметка
  // biome-ignore lint/correctness/useExhaustiveDependencies: сброс именно при смене пункта
  useEffect(() => setNote(""), [itemId]);

  const idx = current ? ordered.indexOf(current) : -1;
  const act = (outcome: Outcome) => {
    if (!current || state === "done") return;
    setAlready(null);
    // после решения — следующий пункт той же группы: документ разбирается подряд
    const n = nextAfter(ordered, current, grouping)?.id ?? null;
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

  const search = (patch: Record<string, string | undefined>) =>
    navigate({ to: "/review", search: { reason, state, group, object, about, who, ...patch } as never });
  const more = (
    <div className="rfilters rfilters--more">
      <select
        className="fld"
        aria-label={t("review.doc")}
        value={object ?? ""}
        onChange={(e) => search({ object: e.target.value || undefined })}
      >
        <option value="">{t("review.all_docs")}</option>
        {facet.docs.map((d) => (
          <option key={d.key} value={d.key}>
            {d.name} · {d.count}
          </option>
        ))}
      </select>
      <select
        className="fld"
        aria-label={t("review.about_f")}
        value={about ?? ""}
        onChange={(e) => search({ about: e.target.value || undefined })}
      >
        <option value="">{t("review.all_about")}</option>
        {facet.about.map((d) => (
          <option key={d.key} value={d.key}>
            {d.name} · {d.count}
          </option>
        ))}
      </select>
      <ToggleButtonGroup
        size="sm"
        selectionMode="single"
        disallowEmptySelection
        selectedKeys={new Set([grouping])}
        onSelectionChange={(k) => search({ group: [...k][0] === "source" ? "source" : undefined })}
        aria-label={t("review.grouping")}
      >
        {(["time", "source"] as const).map((g, i) => (
          <ToggleButton key={g} id={g}>
            {i > 0 && <ToggleButtonGroup.Separator />}
            {t(g === "time" ? "review.by_time" : "review.by_source")}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </div>
  );
  const filters = (
    <div className="rfilters">
      <select
        className="fld"
        aria-label={t("review.reason")}
        value={reason ?? ""}
        onChange={(e) =>
          navigate({
            to: "/review",
            search: { reason: e.target.value || undefined, state, group, object, about, who } as never,
          })
        }
      >
        <option value="">{t("review.any")}</option>
        {REASONS.map((r) => (
          <option key={r} value={r}>
            {t(`review.r.${r}`)}
          </option>
        ))}
      </select>
      <ToggleButtonGroup
        size="sm"
        selectionMode="single"
        disallowEmptySelection
        selectedKeys={new Set([state])}
        onSelectionChange={(k) => {
          const s2 = [...k][0] === "done" ? "done" : undefined;
          navigate({ to: "/review", search: { reason, state: s2, group, object, about, who } as never });
        }}
        aria-label={t("review.state")}
      >
        {(["open", "done"] as const).map((s2, i) => (
          <ToggleButton key={s2} id={s2}>
            {i > 0 && <ToggleButtonGroup.Separator />}
            {t(`review.${s2}`)}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </div>
  );

  return (
    <div className="review" data-item={itemId ? true : undefined}>
      <section className="review__list" aria-labelledby="review-title">
        <h1 id="review-title" className="review__h">
          {t("review.title")}
          {list.data && <span className="count">{items.length}</span>}
        </h1>
        {state === "open" && (
          <>
            <div className="rtabs" role="tablist" aria-label={t("review.tabs")}>
              <button
                type="button"
                role="tab"
                aria-selected={who !== "model"}
                className="rtab"
                onClick={() => navigate({ to: "/review", search: { state: undefined } as never })}
              >
                {t("review.tab_you")}
                <span className="count">{mine.length}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={who === "model"}
                className="rtab"
                onClick={() => navigate({ to: "/review", search: { who: "model" } as never })}
              >
                {t("review.tab_model")}
                <span className="count">{live.length - mine.length}</span>
              </button>
            </div>
            <p className="muted review__intro">
              {who === "model"
                ? verifier?.last_at
                  ? t("review.model_last", {
                      when: new Date(verifier.last_at).toLocaleString(i18n.language, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                      count: verifier.decided ?? 0,
                    })
                  : t("review.model_never")
                : t("review.intro")}
            </p>
          </>
        )}
        {filters}
        {more}
        {capped && <p className="muted review__cap">{t("review.first_n", { n: REVIEW_LIMIT })}</p>}
        {list.isPending ? (
          <RegionState state="loading" />
        ) : list.isError ? (
          <RegionState
            state="error"
            message={errorText(list.error, t("region.offline"))}
            retry={() => list.refetch()}
          />
        ) : ordered.length === 0 ? (
          <RegionState
            state="empty"
            text={
              state === "done"
                ? t("review.empty_done")
                : who === "model"
                  ? t("review.empty_model")
                  : t("review.empty_you")
            }
          />
        ) : (
          <QueueList rows={rows} grouping={grouping} selected={itemId ?? null} onSelect={(id) => go(id)} />
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
              <fieldset className="decide">
                <legend className="sr-only">{t("review.title")}</legend>
                <input
                  className="fld decide__note"
                  aria-label={t("review.note")}
                  placeholder={t("review.note_ph")}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <Button
                  variant="ghost"
                  onPress={skip}
                  aria-label={t("review.skip_k")}
                  aria-describedby="after-skip"
                >
                  {t("review.skip")}
                </Button>
                <Button
                  variant="outline"
                  onPress={() => act("refuted")}
                  aria-label={t("review.refute_k")}
                  aria-describedby="after-refute"
                >
                  {t("review.refute")}
                </Button>
                <Button
                  className="pillbtn"
                  onPress={() => act("confirmed")}
                  aria-label={t("review.confirm_k")}
                  aria-describedby="after-confirm"
                >
                  {t("review.confirm")}
                </Button>
                {/* что будет после каждой кнопки — словами, под кнопками */}
                <ul className="decide__after muted">
                  <li id="after-confirm">
                    {aboutEdit(current.reason) ? t("review.after_confirm_edit") : t("review.after_confirm")}
                  </li>
                  <li id="after-refute">
                    {aboutEdit(current.reason) ? t("review.after_refute_edit") : t("review.after_refute")}
                  </li>
                  <li id="after-skip">{t("review.after_skip")}</li>
                </ul>
              </fieldset>
            )}
          </>
        ) : (
          ordered.length > 0 && <p className="muted review__pick">{t("review.pick")}</p>
        )}
      </section>
    </div>
  );
}
