// Строка фильтров над списком записей: теги (все сразу), вид, статус, объект. Значения — в адресе страницы.
import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useState } from "react";
import { ComboBox, Input, ListBox, ListBoxItem, Popover } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { q, type RecordFilter } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { pickText } from "../../ui/lang";
import { useDebounced, useSuggest } from "../write/Suggest";
import { kindLabel } from "./RecordList";
import "../palette/palette.css";

type Status = components["schemas"]["Status"];
const STATUSES: Status[] = [
  "verified",
  "auto_verified",
  "needs_review",
  "draft",
  "rejected",
  "deprecated",
  "superseded",
];

export const hasFilter = (f: RecordFilter) =>
  !!(f.tag?.length || f.kind?.length || f.status?.length || f.about);

export function TagFilter({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const query = useDebounced(text.trim().replace(/^#/, "").toLowerCase());
  const known = useQuery({ ...q.tags(query), enabled: query.length > 0 });
  const add = (raw: string) => {
    const v = raw.trim().replace(/^#/, "").toLowerCase();
    if (v && !value.includes(v)) onChange([...value, v]);
    setText("");
  };
  const options = (known.data ?? [])
    .filter((x) => !value.includes(x.tag))
    .map((x) => ({ id: x.tag, label: `#${x.tag}`, meta: String(x.count) }));
  const sug = useSuggest(query ? options : [], (o) => add(o.id));
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (sug.onKey(e)) return;
    if (e.key === "Enter") {
      e.preventDefault();
      add(text);
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
      <span className="suggest__wrap">
        <input
          className="fld fld--inline"
          role="combobox"
          aria-expanded={sug.open}
          aria-label={t("filters.tag")}
          value={text}
          placeholder={t("filters.tag_ph")}
          onChange={(e) => {
            setText(e.target.value);
            sug.reopen();
          }}
          onKeyDown={onKey}
          {...sug.fieldProps}
        />
        {sug.list}
      </span>
    </span>
  );
}

function ObjectFilter({ value, onChange }: { value?: string; onChange: (v?: string) => void }) {
  const { t, i18n } = useTranslation();
  const [text, setText] = useState("");
  const query = useDebounced(text);
  const hits = useQuery({ ...q.pick("entity", query), enabled: !value });
  const chosen = useQuery({ ...q.record(value ?? ""), enabled: !!value });
  if (value) {
    const label =
      pickText((chosen.data?.payload as { label?: never } | undefined)?.label, i18n.language) || value;
    return (
      <span className="pill obj" title={label}>
        <span className="pill__t">{label}</span>
        <button
          type="button"
          aria-label={t("edit.remove", { what: label })}
          onClick={() => onChange(undefined)}
        >
          <Icon name="cross" size={12} />
        </button>
      </span>
    );
  }
  const items = hits.data?.items ?? [];
  return (
    <ComboBox
      aria-label={t("filters.object")}
      inputValue={text}
      onInputChange={setText}
      items={items}
      menuTrigger="focus"
      allowsEmptyCollection
      onSelectionChange={(k) => {
        if (k == null) return;
        onChange(String(k));
        setText("");
      }}
      className="refs__box"
    >
      <Input className="fld fld--inline" placeholder={t("filters.object_ph")} />
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
  );
}

/** Фильтры складываются (И); «Сбросить» — только когда что-то выбрано. */
export function RecordFilters({
  value,
  onChange,
}: {
  value: RecordFilter;
  onChange: (f: RecordFilter) => void;
}) {
  const { t, i18n } = useTranslation();
  const kinds = useQuery(q.vocab("kind"));
  const classes = useQuery(q.vocab("entity_class"));
  const set = (patch: Partial<RecordFilter>) => onChange({ ...value, ...patch });
  const kind = value.kind?.[0] ?? "";
  const status = value.status?.[0] ?? "";
  return (
    // biome-ignore lint/a11y/useSemanticElements: строка фильтров списка, не поля формы
    <div className="filters recfilters" role="group" aria-label={t("filters.title")}>
      <TagFilter value={value.tag ?? []} onChange={(tag) => set({ tag })} />
      <select
        className="fld recfilters__sel"
        aria-label={t("filters.kind")}
        value={kind}
        onChange={(e) => set({ kind: e.target.value ? [e.target.value] : [] })}
      >
        <option value="">{t("filters.kind_any")}</option>
        <optgroup label={t("filters.kinds")}>
          {kinds.data?.map((k) => (
            <option key={k.code} value={k.code}>
              {kindLabel(kinds.data, k.code, i18n.language)}
            </option>
          ))}
        </optgroup>
        <optgroup label={t("filters.classes")}>
          {classes.data?.map((k) => (
            <option key={k.code} value={k.code}>
              {kindLabel(classes.data, k.code, i18n.language)}
            </option>
          ))}
        </optgroup>
      </select>
      <select
        className="fld recfilters__sel"
        aria-label={t("filters.status")}
        value={status}
        onChange={(e) => set({ status: e.target.value ? [e.target.value as Status] : [] })}
      >
        <option value="">{t("filters.status_any")}</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {t(`status.${s}`)}
          </option>
        ))}
      </select>
      <ObjectFilter value={value.about} onChange={(about) => set({ about })} />
      {hasFilter(value) && (
        <button type="button" className="chipbtn" onClick={() => onChange({})}>
          {t("filters.reset")}
        </button>
      )}
    </div>
  );
}
