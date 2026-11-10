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
import { type Option, tokenBefore, useDebounced, useSuggest } from "./Suggest";
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
  // объекты, выбранные из подсказки @: плашками «О чём», в тексте их нет
  const [picked, setPicked] = useState<{ ref: string; label: string }[]>([]);
  const [caret, setCaret] = useState(0);
  const tok = tokenBefore(text, caret);
  const tokQuery = useDebounced(tok ? `${tok.kind}${tok.query}` : "");
  const tq = tokQuery.replace(/^(@|#|\[\[)/, "");
  const objHits = useQuery({ ...q.pick("entity", tq), enabled: tokQuery.startsWith("@") });
  const recHits = useQuery({ ...q.pick("atom", tq), enabled: tokQuery.startsWith("[[") && tq.length > 0 });
  const tagHits = useQuery({ ...q.tags(tq), enabled: tokQuery.startsWith("#") });
  const options: Option[] = !tok
    ? []
    : tok.kind === "@"
      ? (objHits.data?.items ?? [])
          .filter((h) => !picked.some((p) => p.ref === h.ref))
          .map((h) => ({ id: h.ref, label: h.label ?? h.ref }))
      : tok.kind === "#"
        ? (tagHits.data ?? []).map((x) => ({ id: x.tag, label: `#${x.tag}`, meta: String(x.count) }))
        : (recHits.data?.items ?? []).map((h) => ({ id: h.ref, label: h.label ?? h.ref }));
  const sug = useSuggest(options, (o) => {
    if (!tok) return;
    const insert = tok.kind === "@" ? "" : tok.kind === "#" ? `#${o.id} ` : `[[${o.label}]] `;
    if (tok.kind === "@") setPicked((p) => [...p, { ref: o.id, label: o.label }]);
    const next = text.slice(0, tok.from) + insert + text.slice(caret);
    const at = tok.from + insert.length;
    setText(next);
    setCaret(at);
    requestAnimationFrame(() => area.current?.setSelectionRange(at, at));
  });
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
    setPicked([]);
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
    const refs = [...new Set([...(about ? [about] : []), ...picked.map((p) => p.ref), ...inferred.about])];
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
    if (sug.onKey(e)) return;
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
          {picked.map((p) => (
            <span key={p.ref} className="pill obj quick__about" title={p.label}>
              <span className="pill__t">{t("quick.about", { what: p.label })}</span>
              <button
                type="button"
                aria-label={t("edit.remove", { what: p.label })}
                onClick={() => setPicked((x) => x.filter((y) => y.ref !== p.ref))}
              >
                <Icon name="cross" size={12} />
              </button>
            </span>
          ))}
          <div className="suggest__wrap quick__textwrap">
            <textarea
              ref={area}
              className="quick__text"
              aria-label={t("quick.text")}
              placeholder={t("quick.placeholder")}
              rows={3}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setCaret(e.target.selectionStart ?? e.target.value.length);
                sug.reopen();
              }}
              onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
              onKeyDown={onKey}
              {...sug.fieldProps}
            />
            {sug.list}
          </div>
          <div className="quick__foot">
            <KindPicker target="atom" value={kind} onChange={(x: Template) => setKindOverride(x.code)} />
            {!kindOverride && inferred.label && (
              <span className="quick__why">{t(`quick.why.${inferred.why}`)}</span>
            )}
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
