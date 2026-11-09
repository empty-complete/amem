import { Button } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { LANGS, type LangString, pickText, withText } from "../../ui/lang";
import { PropertyEditor } from "../write/fields";
import { emptyDraft, type FormField, type Template } from "../write/proposal";
import { slug } from "./slug";
import { kindsStore, useKindsEdit, useKindsOpen } from "./store";
import "./kinds.css";

type Draft = components["schemas"]["TemplateDraft"];
const TYPES: FormField["type"][] = [
  "object",
  "record",
  "text",
  "quantity",
  "date",
  "period",
  "choice",
  "tags",
];
const WIDGETS = ["sources", "links", "around", "values_table", "similar", "children"] as const;

const blankField = (i: number): FormField => ({
  key: `f${i}`,
  path: `qualifiers[property=f${i}]`,
  label: {},
  type: "text",
  required: false,
  hint: null,
  scheme: null,
  property: null,
  unit: null,
  accepts: null,
});

/** Путь свойства в теле записи по его типу: объект — about, величина — content.values, дата — valid_from, остальное — qualifiers. */
function withPath(f: FormField, i: number): FormField {
  const key = f.key || `f${i}`;
  const path =
    f.type === "object"
      ? "about"
      : f.type === "quantity"
        ? `content.values[property=${f.property ?? key}]`
        : f.type === "date" || f.type === "period"
          ? "valid_from"
          : f.type === "tags"
            ? "tags"
            : `qualifiers[property=${key}]`;
  return { ...f, key, path };
}

function FieldRow({
  f,
  i,
  n,
  err,
  onChange,
  onMove,
  onRemove,
}: {
  f: FormField;
  i: number;
  n: number;
  err?: string;
  onChange: (f: FormField) => void;
  onMove: (d: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const classes = useQuery(q.vocab("entity_class"));
  const kinds = useQuery(q.vocab("kind"));
  const props = useQuery(q.vocab("property"));
  const lab = (l: LangString) => pickText(l, i18n.language);
  const toggle = (list: string[] | undefined, v: string) =>
    list?.includes(v) ? list.filter((x) => x !== v) : [...(list ?? []), v];
  return (
    <fieldset className="frow2" data-invalid={err ? true : undefined}>
      <legend className="sr-only">{t("kinds.prop_n", { n: i + 1 })}</legend>
      <div className="frow2__main">
        <input
          className="fld"
          aria-label={t("kinds.prop_name")}
          placeholder={t("kinds.prop_name")}
          value={pickText(f.label, i18n.language)}
          onChange={(e) =>
            onChange({
              ...f,
              label: withText(f.label, e.target.value, i18n.language),
              key: f.key.startsWith("f") ? slug(e.target.value) || f.key : f.key,
            })
          }
        />
        <select
          className="fld"
          aria-label={t("kinds.prop_type")}
          value={f.type}
          onChange={(e) => onChange({ ...f, type: e.target.value as FormField["type"] })}
        >
          {TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`kinds.type_${x}`)}
            </option>
          ))}
        </select>
        <label className="chk">
          <input
            type="checkbox"
            checked={!!f.required}
            onChange={(e) => onChange({ ...f, required: e.target.checked })}
          />
          {t("card.need")}
        </label>
        <span className="frow2__acts">
          <button
            type="button"
            className="iconbtn"
            aria-label={t("kinds.up")}
            disabled={i === 0}
            onClick={() => onMove(-1)}
          >
            ↑
          </button>
          <button
            type="button"
            className="iconbtn"
            aria-label={t("kinds.down")}
            disabled={i === n - 1}
            onClick={() => onMove(1)}
          >
            ↓
          </button>
          <button
            type="button"
            className="iconbtn"
            aria-label={t("edit.remove", {
              what: pickText(f.label, i18n.language) || t("kinds.prop_n", { n: i + 1 }),
            })}
            onClick={onRemove}
          >
            <Icon name="cross" size={12} />
          </button>
        </span>
      </div>
      {err && (
        <p className="fielderr" role="alert">
          {err}
        </p>
      )}
      <input
        className="fld"
        aria-label={t("kinds.hint")}
        placeholder={t("kinds.hint")}
        value={pickText(f.hint, i18n.language)}
        onChange={(e) =>
          onChange({ ...f, hint: e.target.value ? withText(f.hint, e.target.value, i18n.language) : null })
        }
      />
      {f.type === "object" && (
        <fieldset className="chips">
          <legend className="sr-only">{t("kinds.accepts_classes")}</legend>
          {classes.data?.map((c) => (
            <label key={c.code} className="chk">
              <input
                type="checkbox"
                checked={!!f.accepts?.entity_classes?.includes(c.code)}
                onChange={() =>
                  onChange({
                    ...f,
                    accepts: {
                      ...(f.accepts ?? {}),
                      entity_classes: toggle(f.accepts?.entity_classes, c.code),
                    },
                  })
                }
              />
              {lab(c.label)}
            </label>
          ))}
        </fieldset>
      )}
      {f.type === "record" && (
        <fieldset className="chips">
          <legend className="sr-only">{t("kinds.accepts_kinds")}</legend>
          {kinds.data?.map((c) => (
            <label key={c.code} className="chk">
              <input
                type="checkbox"
                checked={!!f.accepts?.kinds?.includes(c.code)}
                onChange={() =>
                  onChange({
                    ...f,
                    accepts: { ...(f.accepts ?? {}), kinds: toggle(f.accepts?.kinds, c.code) },
                  })
                }
              />
              {lab(c.label)}
            </label>
          ))}
        </fieldset>
      )}
      {f.type === "quantity" && (
        <select
          className="fld"
          aria-label={t("edit.quantity")}
          value={f.property ?? ""}
          onChange={(e) => {
            const p = props.data?.find((x) => x.code === e.target.value);
            onChange({
              ...f,
              property: e.target.value || null,
              unit: (p as { unit?: string } | undefined)?.unit ?? null,
            });
          }}
        >
          <option value="">{t("edit.quantity")}</option>
          {props.data?.map((p) => (
            <option key={p.code} value={p.code}>
              {lab(p.label)}
            </option>
          ))}
        </select>
      )}
      {f.type === "choice" && (
        <input
          className="fld"
          aria-label={t("kinds.scheme")}
          placeholder={t("kinds.scheme")}
          value={f.scheme ?? ""}
          onChange={(e) => onChange({ ...f, scheme: e.target.value || null })}
        />
      )}
    </fieldset>
  );
}

/** Конструктор вида (разд. 5.9): свои виды и свойства в пакете «Мои виды»; ничего не зашито. */
export function KindDrawer() {
  const { t, i18n } = useTranslation();
  const open = useKindsOpen();
  const editCode = useKindsEdit();
  const qc = useQueryClient();
  const list = useQuery({ ...q.templates("atom"), enabled: open });
  const mine = (list.data ?? []).filter((x) => x.editable);
  const [code, setCode] = useState<string | null>(null);
  const [codeTouched, setCodeTouched] = useState(false);
  const [d, setD] = useState<Draft | null>(null);
  const [issues, setIssues] = useState<Record<string, string>>({});
  // замечание к подписи — по пути LangString целиком или его слота: label, label.ru, label.en
  const issueAt = (path: string) => issues[path] ?? LANGS.map((l) => issues[`${path}.${l}`]).find(Boolean);
  const labelIssue = issueAt("label");
  const [msg, setMsg] = useState<string | null>(null);

  const startNew = () => {
    setCode("");
    setCodeTouched(false);
    setD({
      label: {},
      target: "atom",
      family: "work",
      form: [],
      body: "wanted",
      widgets: ["sources", "links", "around"],
    });
    setIssues({});
    setMsg(null);
  };
  const startEdit = (x: Template) => {
    setCode(x.code);
    setCodeTouched(true);
    setD({
      label: x.label as Draft["label"],
      target: x.target,
      family: x.family,
      form: x.form,
      body: x.body,
      widgets: x.widgets,
      description: x.description ?? undefined,
    });
    setIssues({});
    setMsg(null);
  };
  // открываем по коду один раз за открытие
  // biome-ignore lint/correctness/useExhaustiveDependencies: список и startEdit не должны переоткрывать форму
  useEffect(() => {
    if (!open) return;
    const x = editCode ? mine.find((m) => m.code === editCode) : null;
    if (x) startEdit(x);
    else if (!editCode) setD(null);
  }, [open, editCode]);

  const preview: Template | undefined = useMemo(
    () =>
      d
        ? ({
            ...d,
            code: code ?? "preview",
            pack: "mine",
            applies_to: code,
            editable: true,
            form: d.form.map(withPath),
          } as Template)
        : undefined,
    [d, code],
  );

  const save = async () => {
    if (!d || !code) return;
    setIssues({});
    setMsg(null);
    try {
      const body = { ...d, form: d.form.map(withPath) };
      const res = await api.PUT("/packs/mine/templates/{code}", { params: { path: { code } }, body });
      if (res.data) {
        await qc.invalidateQueries({ queryKey: ["templates"] });
        await qc.invalidateQueries({ queryKey: ["vocab", "kind"] });
        setMsg(t("kinds.saved", { name: pickText(d.label, i18n.language) }));
      }
    } catch (e) {
      const err = e as ApiError;
      const map: Record<string, string> = {};
      for (const i of err.issues ?? []) map[i.path ?? "_"] = i.message;
      setIssues(map);
      if (!err.issues?.length) setMsg(err.detail ?? err.title);
    }
  };
  const remove = async () => {
    if (!code) return;
    try {
      await api.DELETE("/packs/mine/templates/{code}", { params: { path: { code } } });
      await qc.invalidateQueries({ queryKey: ["templates"] });
      setD(null);
    } catch (e) {
      setMsg((e as ApiError).detail ?? (e as ApiError).title);
    }
  };
  const setForm = (form: FormField[]) => d && setD({ ...d, form });

  return (
    <ModalOverlay
      isOpen={open}
      onOpenChange={(o) => !o && kindsStore.close()}
      isDismissable
      className="modal-overlay drawer-overlay"
    >
      <Modal className="drawer">
        <Dialog className="drawer__in" aria-label={t("kinds.title")}>
          <header className="drawer__head">
            <Heading slot="title">{t("kinds.title")}</Heading>
            <button
              type="button"
              className="iconbtn"
              aria-label={t("sky.close")}
              onClick={() => kindsStore.close()}
            >
              <Icon name="cross" />
            </button>
          </header>
          {!d ? (
            <div className="drawer__body">
              <p className="muted">{t("kinds.intro")}</p>
              <ul className="kinds">
                {mine.map((x) => (
                  <li key={x.code}>
                    <button type="button" className="cite" onClick={() => startEdit(x)}>
                      <span className="cite__main">
                        <span>{pickText(x.label, i18n.language)}</span>
                        <span className="muted">{t("kinds.records", { count: x.records ?? 0 })}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <Button className="pillbtn" onPress={startNew}>
                <Icon name="plus" />
                {t("kinds.new")}
              </Button>
            </div>
          ) : (
            <div className="drawer__body">
              <label className="fl">
                {t("kinds.name")}
                <input
                  className="fld"
                  value={pickText(d.label, i18n.language)}
                  aria-invalid={labelIssue ? true : undefined}
                  onChange={(e) => {
                    setD({ ...d, label: withText(d.label, e.target.value, i18n.language) });
                    if (!codeTouched) setCode(slug(e.target.value));
                  }}
                />
              </label>
              {labelIssue && (
                <p className="fielderr" role="alert">
                  {labelIssue}
                </p>
              )}
              <label className="fl">
                {t("kinds.code")}
                <input
                  className="fld"
                  value={code ?? ""}
                  onChange={(e) => {
                    setCodeTouched(true);
                    setCode(e.target.value.replace(/[^a-z0-9_]/g, ""));
                  }}
                />
              </label>
              <fieldset className="fl fl--row">
                <legend>{t("kinds.family")}</legend>
                {(["source", "work"] as const).map((fam) => (
                  <label key={fam} className="chk">
                    <input
                      type="radio"
                      name="family"
                      checked={d.family === fam}
                      onChange={() => setD({ ...d, family: fam })}
                    />
                    {t(`home.f_${fam}`)}
                  </label>
                ))}
              </fieldset>

              <h3>{t("kinds.props")}</h3>
              {d.form.map((f, i) => (
                <FieldRow
                  // biome-ignore lint/suspicious/noArrayIndexKey: ключ свойства меняется при наборе имени — строка не должна пересоздаваться
                  key={i}
                  f={f}
                  i={i}
                  n={d.form.length}
                  err={issueAt(`form[${i}].label`)}
                  onChange={(nf) => setForm(d.form.map((x, j) => (j === i ? nf : x)))}
                  onMove={(dir) => {
                    const a = [...d.form];
                    const [x] = a.splice(i, 1);
                    if (x) a.splice(i + dir, 0, x);
                    setForm(a);
                  }}
                  onRemove={() => setForm(d.form.filter((_, j) => j !== i))}
                />
              ))}
              <button
                type="button"
                className="addprop"
                onClick={() => setForm([...d.form, blankField(d.form.length + 1)])}
              >
                <Icon name="plus" size={14} />
                {t("kinds.add_prop")}
              </button>

              <fieldset className="fl fl--row">
                <legend>{t("kinds.body")}</legend>
                {(["wanted", "required", "none"] as const).map((b) => (
                  <label key={b} className="chk">
                    <input
                      type="radio"
                      name="body"
                      checked={d.body === b}
                      onChange={() => setD({ ...d, body: b })}
                    />
                    {t(`kinds.body_${b}`)}
                  </label>
                ))}
              </fieldset>
              <fieldset className="fl fl--row">
                <legend>{t("kinds.widgets")}</legend>
                {WIDGETS.map((w) => (
                  <label key={w} className="chk">
                    <input
                      type="checkbox"
                      checked={d.widgets.includes(w)}
                      onChange={(e) =>
                        setD({
                          ...d,
                          widgets: e.target.checked ? [...d.widgets, w] : d.widgets.filter((x) => x !== w),
                        })
                      }
                    />
                    {t(`kinds.w_${w}`)}
                  </label>
                ))}
              </fieldset>

              <section className="kinds__preview" aria-label={t("kinds.preview")}>
                <h3>{t("kinds.preview")}</h3>
                <PropertyEditor
                  template={preview}
                  draft={emptyDraft(code ?? "preview")}
                  labels={{}}
                  issues={{}}
                  onChange={() => {}}
                />
              </section>

              {msg && (
                <p className="muted" role="status">
                  {msg}
                </p>
              )}
              <div className="editor__foot">
                <Button className="pillbtn" isDisabled={!code} onPress={save}>
                  {t("kinds.save")}
                </Button>
                <Button variant="ghost" onPress={() => setD(null)}>
                  {t("kinds.back")}
                </Button>
                {mine.some((m) => m.code === code) && (
                  <Button variant="ghost" className="danger" onPress={remove}>
                    {t("kinds.delete")}
                  </Button>
                )}
              </div>
            </div>
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
