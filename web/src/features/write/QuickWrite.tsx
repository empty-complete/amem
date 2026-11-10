import { useQueries, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import { type LangString, pickText, useText } from "../../ui/lang";
import { draftKey, dropDraft, loadDraft, saveDraft } from "./drafts";
import { infer } from "./infer";
import { KindPicker } from "./KindPicker";
import { placeStore, useQuickOpen, useWritePlace } from "./place";
import { type Draft, emptyDraft, type Template, toProposal } from "./proposal";
import { useSubmit } from "./useSubmit";

/** Окно записи (разд. 5.9, п. 2): одно поле, Enter, звезда. По «N» и по «Записать»; страница остаётся живой. */
export function QuickWrite({ trigger }: { trigger: React.RefObject<HTMLElement | null> }) {
  const { t } = useTranslation();
  const { lang } = useText();
  const open = useQuickOpen();
  const navigate = useNavigate();
  const place = useWritePlace();
  const [aboutOff, setAboutOff] = useState(false);
  const about = aboutOff ? null : place.ref;
  const key = draftKey("new", about);
  const [text, setText] = useState("");
  const [kindOverride, setKindOverride] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const templates = useQuery(q.templates("atom"));
  const props = useQuery(q.vocab("property"));
  // @слово — поиском по всем объектам базы (как «о чём» в полном редакторе); первый ответ и есть объект
  const words = useMemo(
    () => [...new Set([...text.matchAll(/@([\p{L}\p{N}._-]+)/gu)].map((m) => m[1] ?? ""))].filter(Boolean),
    [text],
  );
  const picks = useQueries({ queries: words.map((w) => q.pick("entity", w)) });
  const objects = picks
    .map((p, i) => {
      const hit = p.data?.items[0];
      return hit ? { ref: hit.ref, label: hit.label ?? hit.ref, codes: [words[i] ?? ""] } : null;
    })
    .filter((o) => o !== null);
  const aboutRec = useQuery({ ...q.record(about ?? ""), enabled: !!about && !place.label });
  const aboutLabel =
    place.label ??
    (pickText((aboutRec.data?.payload as { label?: LangString } | undefined)?.label, lang) || about) ??
    "";
  const submit = useSubmit();

  useEffect(() => {
    if (!open) return;
    const d = loadDraft(key);
    setText(d ? [d.label, d.body].filter(Boolean).join("\n") : "");
    setKindOverride(null);
    setTimeout(() => area.current?.focus(), 0);
  }, [open, key]);

  // разбор дешёвый: считаем на каждой отрисовке, объекты приходят из поиска по мере ответа
  const inferred = infer(text, { properties: (props.data ?? []) as never, objects });
  const kind = kindOverride ?? inferred.kind;
  const tpl = templates.data?.find((x) => x.code === kind);

  const toDraft = (): Draft => {
    const d = emptyDraft(kind);
    d.label = inferred.label;
    d.body = inferred.body;
    const refs = [...new Set([...(about ? [about] : []), ...inferred.about])];
    const aboutField = tpl?.form.find((f) => f.path === "about");
    if (aboutField) d.values[aboutField.key] = refs;
    const tagField = tpl?.form.find((f) => f.type === "tags");
    if (tagField && inferred.tags.length) d.values[tagField.key] = inferred.tags;
    const qty = tpl?.form.find((f) => f.type === "quantity");
    if (qty && inferred.quantity)
      d.values[qty.key] = {
        amount: inferred.quantity.amount,
        unit: inferred.quantity.unit,
        property: inferred.quantity.property ?? null,
      };
    return d;
  };

  const panel = useRef<HTMLDivElement>(null);
  const close = () => {
    if (text.trim()) saveDraft(key, toDraft());
    placeStore.openQuick(false);
    trigger.current?.focus();
  };
  // нажатие снаружи закрывает окно (черновик остаётся); подсказки и списки внутри — не снаружи
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const el = e.target as Node;
      if (panel.current?.contains(el) || trigger.current?.contains(el)) return;
      if ((el as Element).closest?.(".palette")) return;
      closeRef.current();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, trigger]);

  const send = () => {
    if (!inferred.label) return;
    const d = toDraft();
    const { proposal } = toProposal(d, tpl);
    submit(
      { proposals: [proposal] },
      {
        label: d.label,
        what: (pickText(tpl?.label, lang) || kind).toLowerCase(),
        kind,
        about: ((d.values.about as string[]) ?? []).filter((r) => r.startsWith("ent:")),
        family: tpl?.family === "source" ? "source" : "work",
        onDone: () => dropDraft(key),
        onIssues: (_, message) => {
          saveDraft(key, d);
          navigate({ to: "/new", search: { about: about ?? undefined, kind, issue: message } as never });
        },
      },
    );
    dropDraft(key);
    setText("");
    placeStore.openQuick(false);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    open && (
      <div
        ref={panel}
        className="quick"
        role="dialog"
        aria-label={t("quick.title")}
        onKeyDown={(e) => e.key === "Escape" && close()}
      >
        <div className="quick__in">
          {about && (
            <span className="pill obj quick__about" title={aboutLabel}>
              <span className="pill__t">{t("quick.about", { what: aboutLabel })}</span>
              <button type="button" aria-label={t("quick.about_off")} onClick={() => setAboutOff(true)}>
                <Icon name="cross" size={12} />
              </button>
            </span>
          )}
          <textarea
            ref={area}
            className="quick__text"
            aria-label={t("quick.text")}
            placeholder={t("quick.placeholder")}
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
          />
          <div className="quick__foot">
            <KindPicker target="atom" value={kind} onChange={(x: Template) => setKindOverride(x.code)} />
            <Button
              className="navlink"
              onPress={() => {
                saveDraft(draftKey("new", about), toDraft());
                placeStore.openQuick(false);
                navigate({ to: "/new", search: { about: about ?? undefined, kind } as never });
              }}
            >
              {t("quick.all_fields")}
            </Button>
            <Button className="pillbtn" isDisabled={!inferred.label} onPress={send}>
              {t("edit.save")}
            </Button>
          </div>
        </div>
      </div>
    )
  );
}
