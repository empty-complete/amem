import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { ComboBox, Input, ListBox, ListBoxItem, Popover } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { unitLabel } from "../../ui/format";
import { Icon, type IconName } from "../../ui/icons";
import { langOf, pickText, useText } from "../../ui/lang";
import type { Draft, FieldValue, FormField, Quantity, Template } from "./proposal";
import "../record/record.css";
import "./write.css";

const ICON: Record<FormField["type"], IconName> = {
  object: "link",
  record: "link",
  quantity: "ruler",
  date: "calendar",
  period: "calendar",
  choice: "stack",
  tags: "tag",
  text: "dash",
};

function useDebounced<T>(v: T, ms = 150) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

/** Ссылки на объекты или записи: плашки с крестиком и поле с подсказками (React Aria ComboBox). */
function RefField({
  f,
  value,
  labels,
  onChange,
}: {
  f: FormField;
  value: string[];
  labels: Record<string, string>;
  onChange: (v: string[], labels: Record<string, string>) => void;
}) {
  const { t } = useTranslation();
  const { lang } = useText();
  const [text, setText] = useState("");
  const query = useDebounced(text);
  const target = f.type === "object" ? "entity" : "atom";
  const hits = useQuery(q.pick(target, query));
  const classes = f.accepts?.entity_classes ?? [];
  const kinds = f.accepts?.kinds ?? [];
  const items = (hits.data?.items ?? []).filter(
    (h) =>
      !value.includes(h.ref) &&
      (!classes.length || !h.entity_class || classes.includes(h.entity_class)) &&
      (!kinds.length || !h.kind || kinds.includes(h.kind)),
  );
  return (
    <span className="refs">
      {value.map((r) => (
        <span key={r} className={`pill ${f.type === "object" ? "obj" : ""}`}>
          {labels[r] ?? r}
          <button
            type="button"
            aria-label={t("edit.remove", { what: labels[r] ?? r })}
            onClick={() =>
              onChange(
                value.filter((x) => x !== r),
                labels,
              )
            }
          >
            <Icon name="cross" size={12} />
          </button>
        </span>
      ))}
      <ComboBox
        aria-label={pickText(f.label, lang)}
        inputValue={text}
        onInputChange={setText}
        items={items}
        menuTrigger="focus"
        allowsEmptyCollection
        onSelectionChange={(k) => {
          const h = items.find((x) => x.ref === k);
          if (!h) return;
          onChange([...value, h.ref], { ...labels, [h.ref]: h.label ?? h.ref });
          setText("");
        }}
        className="refs__box"
      >
        <Input
          className="fld fld--inline"
          placeholder={f.type === "object" ? t("edit.add_object") : t("edit.add_record")}
        />
        <Popover className="palette" placement="bottom start">
          <ListBox className="palette__list">
            {(h: (typeof items)[number]) => (
              <ListBoxItem id={h.ref} textValue={h.label ?? h.ref} className="palette__opt">
                <span className="palette__label">{h.label}</span>
              </ListBoxItem>
            )}
          </ListBox>
        </Popover>
      </ComboBox>
    </span>
  );
}

const UNITS = ["%", "Cel", "K", "hPa", "kPa", "Pa", "s", "min", "h", "V", "A", "W", "m", "mm", "m/s", "1"];

function QuantityField({
  f,
  value,
  onChange,
}: {
  f: FormField;
  value: Quantity;
  onChange: (v: Quantity) => void;
}) {
  const { t, i18n } = useTranslation();
  const props = useQuery(q.vocab("property"));
  const prop = props.data?.find((p) => p.code === (value.property ?? f.property));
  const unit = value.unit ?? f.unit ?? (prop as { unit?: string } | undefined)?.unit ?? "";
  const id = useId();
  const [raw, setRaw] = useState(
    value.amount != null ? String(value.amount).replace(".", ",") : (value.value_text ?? ""),
  );
  return (
    <span className="qty">
      {!f.property && (
        <select
          className="fld"
          aria-label={t("edit.quantity")}
          value={value.property ?? ""}
          onChange={(e) => onChange({ ...value, property: e.target.value || null })}
        >
          <option value="">{t("edit.quantity")}</option>
          {props.data?.map((p) => (
            <option key={p.code} value={p.code}>
              {pickText(p.label, i18n.language)}
            </option>
          ))}
        </select>
      )}
      <input
        id={id}
        className="fld num"
        inputMode="decimal"
        aria-label={pickText(f.label, i18n.language)}
        value={raw}
        placeholder="___"
        onChange={(e) => {
          const v = e.target.value;
          setRaw(v);
          const n = Number(v.replace("−", "-").replace(",", ".").trim());
          if (v.trim() === "") onChange({ ...value, amount: null, value_text: null });
          else if (Number.isFinite(n)) onChange({ ...value, amount: n, value_text: null, unit });
          else onChange({ ...value, amount: null, value_text: v.trim(), unit });
        }}
      />
      <select
        className="fld unit"
        aria-label={t("edit.unit")}
        value={unit}
        onChange={(e) => onChange({ ...value, unit: e.target.value })}
      >
        {[...new Set([unit, ...UNITS].filter(Boolean))].map((u) => (
          <option key={u} value={u}>
            {unitLabel(u, i18n.language) || u}
          </option>
        ))}
      </select>
    </span>
  );
}

function TagsField({
  f,
  value,
  onChange,
}: {
  f: FormField;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const { t } = useTranslation();
  const { lang } = useText();
  const [text, setText] = useState("");
  const add = () => {
    const v = text.trim().replace(/^#/, "").toLowerCase();
    if (v && !value.includes(v)) onChange([...value, v]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
  };
  return (
    <span className="refs">
      {value.map((v) => (
        <span key={v} className="pill">
          #{v}
          <button
            type="button"
            aria-label={t("edit.remove", { what: v })}
            onClick={() => onChange(value.filter((x) => x !== v))}
          >
            <Icon name="cross" size={12} />
          </button>
        </span>
      ))}
      <input
        className="fld fld--inline"
        aria-label={pickText(f.label, lang)}
        value={text}
        placeholder={t("edit.add_tag")}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
      />
    </span>
  );
}

function ChoiceField({ f, value, onChange }: { f: FormField; value: string; onChange: (v: string) => void }) {
  const { i18n } = useTranslation();
  const vocab = useQuery({ ...q.vocab(f.scheme ?? "kind"), enabled: !!f.scheme });
  return (
    <select
      className="fld"
      aria-label={pickText(f.label, i18n.language)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="" />
      {vocab.data?.map((v) => (
        <option key={v.code} value={v.code}>
          {pickText(v.label, i18n.language)}
        </option>
      ))}
    </select>
  );
}

/** Свойства в правке (разд. 5.4): строки «значок типа · имя · значение» по форме шаблона; «+ Свойство» — своё. */
export function PropertyEditor({
  template,
  draft,
  labels,
  issues,
  onChange,
}: {
  template: Template | undefined;
  draft: Draft;
  labels: Record<string, string>;
  issues: Record<string, string>;
  onChange: (d: Draft, labels?: Record<string, string>) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = langOf(i18n.language);
  const set = (key: string, v: FieldValue, l?: Record<string, string>) =>
    onChange({ ...draft, values: { ...draft.values, [key]: v } }, l);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  return (
    <fieldset className="props props--edit">
      <legend className="sr-only">{t("record.props")}</legend>
      {template?.form.map((f) => {
        const v = draft.values[f.key];
        const err = issues[f.key];
        const empty = v == null || v === "" || (Array.isArray(v) && !v.length);
        return (
          <div key={f.key} className="prop" data-invalid={err ? true : undefined}>
            <span className="k">
              <Icon name={ICON[f.type]} size={14} />
              <span>{pickText(f.label, lang)}</span>
            </span>
            <span className="v">
              {f.type === "object" || f.type === "record" ? (
                <RefField
                  f={f}
                  value={(v as string[]) ?? []}
                  labels={labels}
                  onChange={(x, l) => set(f.key, x, l)}
                />
              ) : f.type === "quantity" ? (
                <QuantityField f={f} value={(v as Quantity) ?? {}} onChange={(x) => set(f.key, x)} />
              ) : f.type === "tags" ? (
                <TagsField f={f} value={(v as string[]) ?? []} onChange={(x) => set(f.key, x)} />
              ) : f.type === "choice" ? (
                <ChoiceField f={f} value={(v as string) ?? ""} onChange={(x) => set(f.key, x)} />
              ) : f.type === "date" ? (
                <input
                  type="date"
                  className="fld"
                  aria-label={pickText(f.label, lang)}
                  value={(v as string) ?? ""}
                  onChange={(e) => set(f.key, e.target.value)}
                />
              ) : f.type === "period" ? (
                <span className="qty">
                  <input
                    type="date"
                    className="fld"
                    aria-label={t("edit.from")}
                    value={(v as { from?: string })?.from ?? ""}
                    onChange={(e) => set(f.key, { ...((v as object) ?? {}), from: e.target.value })}
                  />
                  —
                  <input
                    type="date"
                    className="fld"
                    aria-label={t("edit.to")}
                    value={(v as { to?: string })?.to ?? ""}
                    onChange={(e) => set(f.key, { ...((v as object) ?? {}), to: e.target.value })}
                  />
                </span>
              ) : (
                <input
                  className="fld"
                  aria-label={pickText(f.label, lang)}
                  value={(v as string) ?? ""}
                  onChange={(e) => set(f.key, e.target.value)}
                />
              )}
              {f.required && empty && !err && <span className="need">{t("card.need")}</span>}
              {err && (
                <span className="fielderr" role="alert">
                  {err}
                </span>
              )}
            </span>
          </div>
        );
      })}
      {draft.extra.map((x, i) => (
        <div key={x.property} className="prop">
          <span className="k">
            <Icon name="dash" size={14} />
            <span>{x.label}</span>
          </span>
          <span className="v">
            <input
              className="fld"
              aria-label={x.label}
              value={x.value}
              onChange={(e) =>
                onChange({
                  ...draft,
                  extra: draft.extra.map((y, j) => (j === i ? { ...y, value: e.target.value } : y)),
                })
              }
            />
            <button
              type="button"
              className="iconbtn"
              aria-label={t("edit.remove", { what: x.label })}
              onClick={() => onChange({ ...draft, extra: draft.extra.filter((_, j) => j !== i) })}
            >
              <Icon name="cross" size={12} />
            </button>
          </span>
        </div>
      ))}
      {adding ? (
        <div className="prop">
          <span className="k">
            <Icon name="plus" size={14} />
          </span>
          <input
            className="fld"
            // biome-ignore lint/a11y/noAutofocus: поле появилось по нажатию «+ Свойство» — фокус ожидаем
            autoFocus
            aria-label={t("edit.prop_name")}
            placeholder={t("edit.prop_name")}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newName.trim()) {
                e.preventDefault();
                const label = newName.trim();
                const property = label
                  .toLowerCase()
                  .replace(/[^\p{L}\p{N}]+/gu, "_")
                  .replace(/^_|_$/g, "");
                onChange({ ...draft, extra: [...draft.extra, { property, label, value: "" }] });
                setNewName("");
                setAdding(false);
              } else if (e.key === "Escape") setAdding(false);
            }}
            onBlur={() => !newName && setAdding(false)}
          />
        </div>
      ) : (
        <button type="button" className="addprop" onClick={() => setAdding(true)}>
          <Icon name="plus" size={14} />
          {t("edit.add_prop")}
        </button>
      )}
    </fieldset>
  );
}
