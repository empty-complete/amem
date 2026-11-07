import { Button } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { api, data } from "../../api/client";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import { RegionState } from "../../ui/RegionState";
import { documentToRecord, recordToDocument } from "../record/doc";
import type { BodyEditorApi, Suggest } from "./BodyEditor";
import { dropDraft, saveDraft } from "./drafts";
import { PropertyEditor } from "./fields";
import { KindPicker } from "./KindPicker";
import { type Draft, type FieldIssues, issuesToFields, type Template, toProposal } from "./proposal";
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
}

const TOOLS: { key: string; label: string; text: string; run: (e: BodyEditorApi) => void }[] = [
  { key: "b", label: "edit.t_bold", text: "B", run: (e) => e.wrap("**") },
  { key: "i", label: "edit.t_italic", text: "I", run: (e) => e.wrap("*") },
  { key: "code", label: "edit.t_code", text: "</>", run: (e) => e.wrap("`") },
  { key: "h2", label: "edit.t_h2", text: "H2", run: (e) => e.line("## ") },
  { key: "quote", label: "edit.t_quote", text: "❝", run: (e) => e.line("> ") },
  { key: "list", label: "edit.t_list", text: "•", run: (e) => e.line("- ") },
  { key: "link", label: "edit.t_link", text: "[[ ]]", run: (e) => e.wrap("[[", "]]") },
  { key: "math", label: "edit.t_math", text: "∑", run: (e) => e.wrap("$") },
];

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

  const suggest: Suggest = useMemo(() => {
    const pick = async (target: "atom" | "entity", s: string) =>
      ((await qc.fetchQuery(q.pick(target, s))).items ?? []).map((h) => h.label ?? h.ref);
    return {
      records: (s) => pick("atom", s),
      objects: (s) => pick("entity", s),
      tags: async (s) =>
        (data(await api.GET("/vocab/{scheme}", { params: { path: { scheme: "tag" } } })) ?? [])
          .map((x) => x.code)
          .filter((c) => c.startsWith(s.toLowerCase())),
    };
  }, [qc]);

  const toSource = () => {
    setSourceText(
      recordToDocument(
        {
          kind: d.kind,
          label: { ru: d.label },
          summary_plain: { ru: d.summary },
          body: { ru: d.body },
          tags: (d.values.tags as string[]) ?? [],
          basis: d.basis,
          qualifiers: d.extra.map((x) => ({
            property: x.property,
            label: { ru: x.label },
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
  const fromSource = () => {
    try {
      const r = documentToRecord(sourceText);
      const extra = Object.entries(r.qualifiers).map(([property, value]) => ({
        property,
        label: d.extra.find((x) => x.property === property)?.label ?? property,
        value,
      }));
      change({
        ...d,
        kind: r.kind,
        label: r.label,
        summary: r.summary_plain,
        body: r.body,
        extra,
        values: { ...d.values, tags: r.tags },
        sources:
          r.quote && d.sources[0] ? [{ ...d.sources[0], quote: r.quote }, ...d.sources.slice(1)] : d.sources,
      });
      setSource(false);
    } catch (e) {
      setSourceErr(t("edit.source_bad", { error: (e as Error).message.split("\n")[0] }));
    }
  };

  const save = () => {
    if (source) {
      fromSource();
      return;
    }
    const resolve = (label: string) => Object.entries(labels).find(([, l]) => l === label)?.[0];
    const { proposal, links } = toProposal(d, tpl, { recordId: p.recordId, base: p.base, resolve });
    const about = ((d.values.about as string[]) ?? []).filter((r) => r.startsWith("ent:"));
    submit(
      { proposals: [proposal], links },
      {
        label: d.label,
        what: (tpl?.label.ru ?? d.kind).toLowerCase(),
        kind: d.kind,
        about,
        family: tpl?.family === "source" ? "source" : "work",
        onDone: () => dropDraft(p.draftKey),
        onIssues: (list, message) => {
          const f = issuesToFields(list, tpl);
          if (!list.length) f.other.push(message);
          p.onRejected?.(d, f);
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
        save();
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
      <input
        className="title title--edit"
        aria-label={t("edit.title")}
        placeholder={t("edit.title_ph")}
        value={d.label}
        aria-invalid={issues?.label ? true : undefined}
        onChange={(e) => change({ ...d, label: e.target.value })}
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
          <textarea
            className="fld lede--edit"
            aria-label={t("edit.summary")}
            placeholder={t("edit.summary_ph")}
            rows={2}
            value={d.summary}
            onChange={(e) => change({ ...d, summary: e.target.value })}
          />
          {tpl?.body === "none" ? (
            <p className="muted">{t("edit.no_body")}</p>
          ) : (
            <div className="bodyedit">
              <div className="toolbar" role="toolbar" aria-label={t("edit.toolbar")}>
                {TOOLS.map((x) => (
                  <button
                    key={x.key}
                    type="button"
                    className="tb"
                    aria-label={t(x.label)}
                    title={t(x.label)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.current && x.run(editor.current)}
                  >
                    {x.text}
                  </button>
                ))}
              </div>
              <Suspense fallback={<RegionState state="loading" />}>
                <BodyEditor
                  ref={editor}
                  value={d.body}
                  onChange={(v) => change({ ...d, body: v })}
                  label={t("edit.body")}
                  placeholder={tpl?.body === "required" ? t("edit.body_required") : t("edit.body_ph")}
                  suggest={suggest}
                  onSubmit={save}
                />
              </Suspense>
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
        <span className="muted editor__keys">{t("edit.keys")}</span>
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
