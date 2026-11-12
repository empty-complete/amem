import { Button } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Dialog,
  Heading,
  Keyboard,
  Menu,
  MenuItem,
  Modal,
  ModalOverlay,
  Popover,
  Separator,
  SubmenuTrigger,
} from "react-aria-components";
import { useTranslation } from "react-i18next";
import { api, data } from "../../api/client";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import { langString, pickText } from "../../ui/lang";
import { MOD } from "../../ui/platform";
import { RegionState } from "../../ui/RegionState";
import { documentToRecord, recordToDocument } from "../record/doc";
import type { BodyEditorApi, Hit, Suggest } from "./BodyEditor";
import { dropDraft, saveDraft } from "./drafts";
import { PropertyEditor } from "./fields";
import { KindPicker } from "./KindPicker";
import { type Draft, type FieldIssues, issuesToFields, type Template, toProposal } from "./proposal";
import { SourcePicker } from "./SourcePicker";
import { SourcesEditor } from "./SourcesEditor";
import { useSubmit } from "./useSubmit";
import "./write.css";

const BodyEditor = lazy(() => import("./BodyEditor"));

export interface RecordEditorProps {
  initial: Draft;
  labels?: Record<string, string>;
  recordId?: string | null;
  base?: Record<string, unknown>;
  draftKey: string;
  /** Пакет ушёл в очередь (окно отмены); ref появится в onDone. */
  onQueued: () => void;
  onCancel: () => void;
  onConfigure?: () => void;
  issues?: FieldIssues | null;
  /** Отказ проверки после окна отмены — вернуть человека в правку с замечаниями. */
  onRejected?: (d: Draft, issues: FieldIssues) => void;
  /** Связи, которые добавить к новой записи (например, «Записать своё рядом» → see_also). */
  extraLinks?: { src: string; dst: string; rel: string }[];
  /** Папка новой записи («» — корень); без неё — из настроек. */
  folder?: string;
}

type Cmd = { key: string; label: string; keys?: string; run: (e: BodyEditorApi) => void };

/** Команды меню по правой кнопке — как в Obsidian: ссылка, «Формат», «Абзац», «Вставить», буфер обмена. */
const FORMAT: Cmd[] = [
  { key: "b", label: "edit.t_bold", keys: "B", run: (e) => e.wrap("**") },
  { key: "i", label: "edit.t_italic", keys: "I", run: (e) => e.wrap("*") },
  { key: "s", label: "edit.t_strike", run: (e) => e.wrap("~~") },
  { key: "hl", label: "edit.t_highlight", run: (e) => e.wrap("==") },
  { key: "code", label: "edit.t_code", run: (e) => e.wrap("`") },
  { key: "math", label: "edit.t_math", run: (e) => e.wrap("$") },
];
const PARAGRAPH: Cmd[] = [
  { key: "h1", label: "edit.t_h1", run: (e) => e.heading(1) },
  { key: "h2", label: "edit.t_h2", run: (e) => e.heading(2) },
  { key: "h3", label: "edit.t_h3", run: (e) => e.heading(3) },
  { key: "list", label: "edit.t_list", run: (e) => e.line("- ") },
  { key: "olist", label: "edit.t_olist", run: (e) => e.line("1. ") },
  { key: "task", label: "edit.t_task", run: (e) => e.line("- [ ] ") },
  { key: "quote", label: "edit.t_quote", run: (e) => e.line("> ") },
];
const INSERT: Cmd[] = [
  { key: "wiki", label: "edit.t_link", keys: "K", run: (e) => e.wrap("[[", "]]") },
  { key: "mathblock", label: "edit.t_mathblock", run: (e) => e.insert("\n$$\n\n$$\n") },
  { key: "table", label: "edit.t_table", run: (e) => e.insert("\n| | |\n|---|---|\n| | |\n") },
  { key: "hr", label: "edit.t_hr", run: (e) => e.insert("\n---\n") },
];
const ALL = [...FORMAT, ...PARAGRAPH, ...INSERT];

/** Меню в точке правого щелчка: React Aria Menu с подменю (стрелки, Enter, Esc) у невидимой опоры. */
function FormatMenu({
  at,
  hasSelection,
  onClose,
  onPick,
}: {
  at: { x: number; y: number } | null;
  hasSelection: boolean;
  onClose: () => void;
  onPick: (key: string) => void;
}) {
  const { t } = useTranslation();
  const anchor = useRef<HTMLSpanElement>(null);
  const item = (c: Cmd) => (
    <MenuItem key={c.key} id={c.key} textValue={t(c.label)} className="palette__opt ctxmenu__opt">
      <span className="palette__label">{t(c.label).replace(/, .*$/, "")}</span>
      {c.keys && <Keyboard className="palette__meta">{`${MOD}${c.keys}`}</Keyboard>}
    </MenuItem>
  );
  const sub = (id: string, label: string, list: Cmd[]) => (
    <SubmenuTrigger>
      <MenuItem id={id} textValue={label} className="palette__opt ctxmenu__opt">
        <span className="palette__label">{label}</span>
        <span className="palette__meta" aria-hidden="true">
          ›
        </span>
      </MenuItem>
      <Popover className="palette ctxmenu" offset={-4}>
        <Menu aria-label={label} className="palette__list" onAction={(k) => onPick(String(k))}>
          {list.map(item)}
        </Menu>
      </Popover>
    </SubmenuTrigger>
  );
  return (
    <>
      <span ref={anchor} aria-hidden="true" className="ctx__anchor" style={{ left: at?.x, top: at?.y }} />
      <Popover
        triggerRef={anchor}
        isOpen={!!at}
        onOpenChange={(o) => !o && onClose()}
        placement="bottom start"
        offset={4}
        className="palette ctxmenu"
      >
        <Menu
          aria-label={t("edit.toolbar")}
          autoFocus="first"
          className="palette__list"
          disabledKeys={hasSelection ? [] : ["cut", "copy"]}
          onAction={(k) => onPick(String(k))}
        >
          <MenuItem id="wiki" textValue={t("edit.m_link")} className="palette__opt ctxmenu__opt">
            <span className="palette__label">{t("edit.m_link")}</span>
            <Keyboard className="palette__meta">{`${MOD}K`}</Keyboard>
          </MenuItem>
          <Separator className="ctxmenu__sep" />
          {sub("format", t("edit.m_format"), FORMAT)}
          {sub("paragraph", t("edit.m_paragraph"), PARAGRAPH)}
          {sub("insert", t("edit.m_insert"), INSERT)}
          <Separator className="ctxmenu__sep" />
          <MenuItem id="cut" textValue={t("edit.m_cut")} className="palette__opt ctxmenu__opt">
            <span className="palette__label">{t("edit.m_cut")}</span>
            <Keyboard className="palette__meta">{`${MOD}X`}</Keyboard>
          </MenuItem>
          <MenuItem id="copy" textValue={t("edit.m_copy")} className="palette__opt ctxmenu__opt">
            <span className="palette__label">{t("edit.m_copy")}</span>
            <Keyboard className="palette__meta">{`${MOD}C`}</Keyboard>
          </MenuItem>
          <MenuItem id="paste" textValue={t("edit.m_paste")} className="palette__opt ctxmenu__opt">
            <span className="palette__label">{t("edit.m_paste")}</span>
            <Keyboard className="palette__meta">{`${MOD}V`}</Keyboard>
          </MenuItem>
          <MenuItem id="all" textValue={t("edit.m_all")} className="palette__opt ctxmenu__opt">
            <span className="palette__label">{t("edit.m_all")}</span>
            <Keyboard className="palette__meta">{`${MOD}A`}</Keyboard>
          </MenuItem>
        </Menu>
      </Popover>
    </>
  );
}

/** Команда меню над редактором: оформление, вставка, буфер обмена. */
async function runMenu(key: string, e: BodyEditorApi) {
  const cmd = ALL.find((c) => c.key === key);
  if (cmd) return cmd.run(e);
  if (key === "all") return e.selectAll();
  if (key === "copy" || key === "cut") {
    await navigator.clipboard?.writeText(e.selection()).catch(() => undefined);
    if (key === "cut") e.insert("");
    else e.focus();
    return;
  }
  if (key === "paste") {
    const text = await navigator.clipboard?.readText().catch(() => "");
    if (text) e.insert(text);
    else e.focus();
  }
}

/** Правка записи (разд. 5.4) — тот же экран, что чтение: заголовок, вид, свойства, тело, источники. */
export function RecordEditor(p: RecordEditorProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const qc = useQueryClient();
  const templates = useQuery(q.templates(p.initial.target));
  const [d, setD] = useState<Draft>(p.initial);
  const [labels, setLabels] = useState<Record<string, string>>(p.labels ?? {});
  const [source, setSource] = useState(false);
  const [sourceText, setSourceText] = useState("");
  const [sourceErr, setSourceErr] = useState<string | null>(null);
  const issues = p.issues ?? null;
  const [asking, setAsking] = useState(false);
  const [picking, setPicking] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const dirty = useRef(false);
  const editor = useRef<BodyEditorApi>(null);
  const submit = useSubmit();
  const tpl = templates.data?.find((x) => x.code === d.kind);

  const change = useCallback(
    (next: Draft, l?: Record<string, string>) => {
      dirty.current = true;
      setD(next);
      if (l) setLabels(l);
      saveDraft(p.draftKey, next);
    },
    [p.draftKey],
  );

  // подсказки @, # и [[: выбор запоминает, на какую запись ссылается [[подпись]] (связь при записи), а @объект
  // ещё и кладёт в «О чём», если у вида есть такое поле
  const aboutKey = tpl?.form.find((f) => f.path === "about")?.key;
  const pickRef = useRef<(hit: Hit, via: "[[" | "@") => void>(() => {});
  pickRef.current = (hit, via) => {
    setLabels((prev) => ({ ...prev, [hit.ref]: hit.label }));
    if (via === "@" && hit.ref.startsWith("ent:") && aboutKey) {
      setD((prev) => {
        const cur = (prev.values[aboutKey] as string[] | undefined) ?? [];
        if (cur.includes(hit.ref)) return prev;
        const next = { ...prev, values: { ...prev.values, [aboutKey]: [...cur, hit.ref] } };
        saveDraft(p.draftKey, next);
        return next;
      });
    }
  };
  const suggest: Suggest = useMemo(() => {
    const pick = async (target: "atom" | "entity", s: string) =>
      ((await qc.fetchQuery(q.pick(target, s))).items ?? []).map((h) => ({
        ref: h.ref,
        label: h.label ?? h.ref,
      }));
    return {
      records: (s) => pick("atom", s),
      objects: (s) => pick("entity", s),
      tags: async (s) =>
        (data(await api.GET("/vocab/{scheme}", { params: { path: { scheme: "tag" } } })) ?? [])
          .map((x) => x.code)
          .filter((c) => c.startsWith(s.toLowerCase())),
      onPick: (hit, via) => pickRef.current(hit, via),
    };
  }, [qc]);

  /** [[подписи]] текста без известной ссылки — по точному названию записи или объекта в базе (как в Obsidian). */
  const resolveWiki = async (body: string, known: Record<string, string>) => {
    const out = { ...known };
    const have = new Set(Object.values(out).map((l) => l.toLowerCase()));
    const want = [
      ...new Set([...body.matchAll(/\[\[([^\]\n|]+)(?:\|[^\]\n]*)?\]\]/g)].map((m) => (m[1] ?? "").trim())),
    ].filter((l) => l && !have.has(l.toLowerCase()));
    for (const label of want) {
      for (const target of ["atom", "entity"] as const) {
        const items = (await qc.fetchQuery(q.pick(target, label)).catch(() => ({ items: [] }))).items ?? [];
        const hit = items.find((h) => (h.label ?? "").trim().toLowerCase() === label.toLowerCase());
        if (hit && hit.ref !== p.recordId) {
          out[hit.ref] = hit.label ?? label;
          break;
        }
      }
    }
    return out;
  };

  const toSource = () => {
    setSourceText(
      recordToDocument(
        {
          kind: d.kind,
          label: langString(d.label, lang),
          summary_plain: langString(d.summary, lang),
          body: langString(d.body, lang),
          tags: (d.values.tags as string[]) ?? [],
          basis: d.basis,
          qualifiers: d.extra.map((x) => ({
            property: x.property,
            label: langString(x.label, lang),
            value_text: x.value,
          })),
        },
        ((d.values.about as string[]) ?? []).map((r) => ({ ref: r, label: labels[r] ?? r })),
        d.sources as never,
        lang,
      ),
    );
    setSourceErr(null);
    setSource(true);
  };
  const fromSource = (): Draft | null => {
    try {
      const r = documentToRecord(sourceText);
      const extra = Object.entries(r.qualifiers).map(([property, value]) => ({
        property,
        label: d.extra.find((x) => x.property === property)?.label ?? property,
        value,
      }));
      const next: Draft = {
        ...d,
        kind: r.kind,
        label: r.label,
        summary: r.summary_plain,
        body: r.body,
        extra,
        values: { ...d.values, tags: r.tags },
        sources:
          r.quote && d.sources[0] ? [{ ...d.sources[0], quote: r.quote }, ...d.sources.slice(1)] : d.sources,
      };
      change(next);
      setSource(false);
      return next;
    } catch (e) {
      setSourceErr(t("edit.source_bad", { error: (e as Error).message.split("\n")[0] }));
      return null;
    }
  };

  const saving = useRef(false);
  const save = async () => {
    // из исходника записывается сразу, а не только переводится обратно в правку (раньше нужно было два нажатия)
    const draft: Draft | null = source ? fromSource() : d;
    if (!draft || saving.current) return;
    saving.current = true;
    const known = await resolveWiki(draft.body, labels).finally(() => {
      saving.current = false;
    });
    const resolve = (label: string) =>
      Object.entries(known).find(([, l]) => l.trim().toLowerCase() === label.trim().toLowerCase())?.[0];
    const { proposal, links } = toProposal(draft, tpl, { recordId: p.recordId, base: p.base, resolve });
    const about = ((draft.values.about as string[]) ?? []).filter((r) => r.startsWith("ent:"));
    submit(
      { proposals: [proposal], links: [...links, ...(p.extraLinks ?? [])] },
      {
        label: draft.label,
        what: (pickText(tpl?.label, lang) || draft.kind).toLowerCase(),
        kind: draft.kind,
        about,
        family: tpl?.family === "source" ? "source" : "work",
        folder: p.folder,
        onDone: () => dropDraft(p.draftKey),
        onIssues: (list, message) => {
          const f = issuesToFields(list, tpl);
          if (!list.length) f.other.push(message);
          p.onRejected?.(draft, f);
        },
      },
    );
    dirty.current = false;
    p.onQueued();
  };

  const cancel = () => {
    if (dirty.current) setAsking(true);
    else p.onCancel();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "Enter") {
        e.preventDefault();
        void save();
      } else if (mod && e.code === "Backslash") {
        e.preventDefault();
        if (source) fromSource();
        else toSource();
      } else if (e.key === "Escape" && !document.querySelector("[data-rac][role=dialog], .palette")) {
        cancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (templates.isPending) return <RegionState state="loading" />;

  return (
    <div className="editor">
      {issues?.other.length ? (
        <p className="fielderr" role="alert">
          {issues.other.join(" ")}
        </p>
      ) : null}
      {/* заголовок переносится, как при чтении; Enter — к тексту, а не новая строка */}
      <textarea
        className="title title--edit"
        rows={1}
        aria-label={t("edit.title")}
        placeholder={t("edit.title_ph")}
        value={d.label}
        aria-invalid={issues?.label ? true : undefined}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
            e.preventDefault();
            editor.current?.focus();
          }
        }}
        onChange={(e) => change({ ...d, label: e.target.value.replace(/\n+/g, " ") })}
      />
      {issues?.label && (
        <p className="fielderr" role="alert">
          {issues.label}
        </p>
      )}
      <div className="editor__kind">
        <span className="muted">{t("record.p_kind")}</span>
        <KindPicker
          target={d.target}
          value={d.kind}
          onConfigure={p.onConfigure}
          onChange={(nt: Template) => {
            // общие ключи формы переезжают в новый вид, остальное остаётся в черновике
            const keep = Object.fromEntries(
              Object.entries(d.values).filter(([k]) => nt.form.some((f) => f.key === k)),
            );
            change({ ...d, kind: nt.code, values: keep });
          }}
        />
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={source}
          onPress={() => (source ? fromSource() : toSource())}
        >
          <Icon name="code" />
          {t("record.mode_source")}
        </Button>
      </div>

      {source ? (
        <>
          {sourceErr && (
            <p className="fielderr" role="alert">
              {sourceErr}
            </p>
          )}
          <Suspense fallback={<RegionState state="loading" />}>
            <BodyEditor
              value={sourceText}
              onChange={setSourceText}
              label={t("record.source_view")}
              placeholder=""
              suggest={suggest}
              onSubmit={save}
            />
          </Suspense>
        </>
      ) : (
        <>
          <PropertyEditor
            template={tpl}
            draft={d}
            labels={labels}
            issues={issues?.fields ?? {}}
            onChange={change}
          />
          {tpl?.body === "none" ? (
            <p className="muted">{t("edit.no_body")}</p>
          ) : (
            <div className="bodyedit">
              <Suspense fallback={<RegionState state="loading" />}>
                <BodyEditor
                  ref={editor}
                  value={d.body}
                  onChange={(v) => change({ ...d, body: v })}
                  label={t("edit.body")}
                  placeholder={tpl?.body === "required" ? t("edit.body_required") : t("edit.body_ph")}
                  suggest={suggest}
                  onSubmit={save}
                  onMenu={setMenu}
                  live
                />
              </Suspense>
              <FormatMenu
                at={menu}
                hasSelection={!!menu && !!editor.current?.selection()}
                onClose={() => setMenu(null)}
                onPick={(k) => {
                  setMenu(null);
                  // после закрытия меню: фокус и выделение возвращаются в текст
                  requestAnimationFrame(() => editor.current && void runMenu(k, editor.current));
                }}
              />
              {issues?.body && (
                <p className="fielderr" role="alert">
                  {issues.body}
                </p>
              )}
            </div>
          )}
          <SourcesEditor
            sources={d.sources}
            issues={issues?.sources ?? {}}
            onChange={(s) => change({ ...d, sources: s })}
            onAdd={() => setPicking(true)}
          />
          <SourcePicker
            open={picking}
            onClose={() => setPicking(false)}
            onPick={(s) => change({ ...d, sources: [...d.sources, s] })}
          />
        </>
      )}

      <div className="editor__foot">
        <Button className="pillbtn" onPress={save}>
          {t("edit.save")}
        </Button>
        <Button variant="ghost" onPress={cancel}>
          {t("edit.cancel")}
        </Button>
        <span className="editor__keys">
          <kbd>{MOD}Enter</kbd> {t("edit.k_save")} <kbd>{MOD}\\</kbd> {t("edit.k_source")} <kbd>Esc</kbd>{" "}
          {t("edit.k_leave")}
        </span>
      </div>

      <ModalOverlay isOpen={asking} onOpenChange={setAsking} isDismissable className="modal-overlay">
        <Modal className="modal">
          <Dialog role="alertdialog" className="modal__in">
            <Heading slot="title">{t("edit.leave_title")}</Heading>
            <p>{t("edit.leave_text")}</p>
            <div className="editor__foot">
              <Button className="pillbtn" onPress={() => setAsking(false)}>
                {t("edit.leave_stay")}
              </Button>
              <Button
                variant="ghost"
                onPress={() => {
                  setAsking(false);
                  dropDraft(p.draftKey);
                  p.onCancel();
                }}
              >
                {t("edit.leave_drop")}
              </Button>
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </div>
  );
}
