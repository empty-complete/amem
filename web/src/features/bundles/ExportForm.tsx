import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api/auth";
import { api } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { FileLink } from "../../ui/FileLink";
import { Icon } from "../../ui/icons";
import { type LangString, pickText } from "../../ui/lang";
// форма открывается и из списка записей (выгрузка выбранного) — стили свои, не только со страницы «Подборки»
import "../kinds/kinds.css";
import "../review/review.css";
import "../write/write.css";
import "./bundles.css";

type Status = components["schemas"]["Status"];
const STATUSES: Status[] = ["verified", "auto_verified", "needs_review", "draft", "deprecated", "superseded"];
type Result = {
  id: string;
  summary: { counts?: Record<string, number> };
  download: string;
  report: string | null;
};

/** Имя zip по умолчанию — как у службы (api._filename): заголовок без опасных знаков, иначе amemo-<id>. */
const zipName = (title: string, id: string) => {
  const name = title
    .normalize("NFC")
    .replace(/[^\p{L}\p{N} \-_.()]/gu, "_")
    .replace(/\s+/g, " ")
    .replace(/_+/g, "_")
    .replace(/^[ ._]+|[ ._]+$/g, "");
  return `${name || `amemo-${id}`}.zip`;
};

/** Отчёт подборки — в окне приложения, а не в новом окне (в приложении его нет): HTML службы без скриптов,
 * в изолированной рамке. */
function ReportButton({ href }: { href: string }) {
  const { t } = useTranslation();
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const open = async () => {
    setErr(null);
    const r = await apiFetch(href).catch((e: Error) => e);
    if (r instanceof Error || !r.ok) return setErr(t("bundles.report_failed"));
    // скрипты отчёта и так не исполнялись (служба отдаёт его с CSP sandbox): убираем, чтобы рамка не ругалась
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    for (const el of doc.querySelectorAll("script")) el.remove();
    setHtml(`<!doctype html>${doc.documentElement.outerHTML}`);
  };
  return (
    <>
      <Button variant="ghost" onPress={() => void open()}>
        <Icon name="external" />
        {t("bundles.report")}
      </Button>
      {err && (
        <span className="fielderr" role="alert">
          {err}
        </span>
      )}
      <ModalOverlay
        isOpen={html != null}
        onOpenChange={(o) => !o && setHtml(null)}
        isDismissable
        className="modal-overlay"
      >
        <Modal className="modal modal--wide">
          <Dialog className="modal__in report" aria-label={t("bundles.report_title")}>
            <Heading slot="title">{t("bundles.report_title")}</Heading>
            <iframe
              className="report__frame"
              title={t("bundles.report_title")}
              sandbox=""
              srcDoc={html ?? ""}
            />
            <div className="editor__foot">
              <Button slot="close" variant="ghost" onPress={() => setHtml(null)}>
                {t("window.close")}
              </Button>
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </>
  );
}

/** Экспорт (разд. 5.10): отбор, «с файлами», «с пакетами и моими видами», готовый отбор «Антология».
 * refs — выбранные в списке записи: отбор — ровно они (поля отбора скрыты), статусы — любые. */
export function ExportForm({ refs, share = false }: { refs?: string[]; share?: boolean } = {}) {
  const { t, i18n } = useTranslation();
  const kinds = useQuery(q.vocab("kind"));
  const classes = useQuery(q.vocab("entity_class"));
  const projects = useQuery({
    ...q.records(null),
    select: (d) => d.items.filter((r) => r.kind_or_class === "project"),
  });
  const [anthology, setAnthology] = useState(false);
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [project, setProject] = useState("");
  const [kindSel, setKindSel] = useState<string[]>([]);
  const [classSel, setClassSel] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<Status[]>(
    STATUSES.filter((s) => s !== "superseded" && s !== "deprecated"),
  );
  const [since, setSince] = useState("");
  // «Поделиться» — подборка, которую другой человек импортирует целиком: с исходными файлами
  const [withFiles, setWithFiles] = useState(share);
  const [withPacks, setWithPacks] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const lab = (l: LangString) => pickText(l, i18n.language);
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const build = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.POST("/bundles/export", {
        body: {
          selection: refs
            ? { refs, statuses: [...STATUSES, "rejected"] }
            : {
                tags: tags
                  .split(/[,\s]+/)
                  .map((x) => x.replace(/^#/, "").trim())
                  .filter(Boolean),
                project: project || null,
                kinds: kindSel,
                entity_classes: classSel,
                statuses: anthology ? ["verified"] : statuses,
                since: since ? new Date(since).toISOString() : null,
              },
          with_files: withFiles,
          // антология пакеты не копирует (служба отвечает 400): у получателя нужны те же пакеты
          with_packs: withPacks && !anthology,
          anthology,
          ...(anthology && title.trim() ? { title: title.trim() } : {}),
        },
      });
      if (r.data) setRes(r.data as Result);
    } catch (e) {
      const a = e as ApiError;
      setErr(a.detail ? `${a.title}: ${a.detail}` : (a.title ?? String(e)));
    } finally {
      setBusy(false);
    }
  };

  if (res) {
    const c = res.summary.counts ?? {};
    return (
      <section className="bdone" aria-labelledby="bdone-title">
        <h2 id="bdone-title">
          <Icon name="check" /> {t("bundles.done")}
        </h2>
        <p>
          {t("bundles.counts", {
            atoms: c.atoms ?? 0,
            entities: c.entities ?? 0,
            links: c.links ?? 0,
            objects: c.objects ?? 0,
          })}
        </p>
        <div className="editor__foot">
          <FileLink className="pillbtn" href={res.download} download={zipName(title, res.id)}>
            {t("bundles.download")}
          </FileLink>
          {res.report && <ReportButton href={res.report} />}
          <Button variant="ghost" onPress={() => setRes(null)}>
            {t("bundles.again")}
          </Button>
        </div>
      </section>
    );
  }

  return (
    <form
      className="bform"
      onSubmit={(e) => {
        e.preventDefault();
        void build();
      }}
    >
      <label className="chk bpreset">
        <input type="checkbox" checked={anthology} onChange={(e) => setAnthology(e.target.checked)} />
        <span>
          <strong>{t("bundles.anthology")}</strong>
          <span className="muted">{t("bundles.anthology_hint")}</span>
        </span>
      </label>
      {anthology && (
        <label className="fl">
          {t("bundles.anthology_title")}
          <input
            className="fld"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Антология"
          />
        </label>
      )}
      {refs ? (
        <p className="bpicked">{t("bundles.picked", { count: refs.length })}</p>
      ) : (
        <fieldset className="bgroup">
          <legend>{t("bundles.selection")}</legend>
          <label className="fl">
            {t("bundles.tags")}
            <input
              className="fld"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder={t("bundles.tags_ph")}
            />
          </label>
          <label className="fl">
            {t("bundles.project")}
            <select className="fld" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">{t("bundles.any_project")}</option>
              {projects.data?.map((p) => (
                <option key={p.ref} value={p.ref}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="fl fl--row">
            <legend>{t("bundles.kinds")}</legend>
            {kinds.data?.map((k) => (
              <label key={k.code} className="chk">
                <input
                  type="checkbox"
                  checked={kindSel.includes(k.code)}
                  onChange={() => setKindSel(toggle(kindSel, k.code))}
                />
                {lab(k.label)}
              </label>
            ))}
          </fieldset>
          <fieldset className="fl fl--row">
            <legend>{t("bundles.classes")}</legend>
            {classes.data?.map((k) => (
              <label key={k.code} className="chk">
                <input
                  type="checkbox"
                  checked={classSel.includes(k.code)}
                  onChange={() => setClassSel(toggle(classSel, k.code))}
                />
                {lab(k.label)}
              </label>
            ))}
          </fieldset>
          <fieldset className="fl fl--row" disabled={anthology}>
            <legend>{t("bundles.statuses")}</legend>
            {STATUSES.map((s) => (
              <label key={s} className="chk">
                <input
                  type="checkbox"
                  checked={anthology ? s === "verified" : statuses.includes(s)}
                  onChange={() => setStatuses(toggle(statuses, s))}
                />
                {t(`status.${s}`)}
              </label>
            ))}
          </fieldset>
          <label className="fl">
            {t("bundles.since")}
            <input className="fld" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          </label>
        </fieldset>
      )}
      <label className="chk">
        <input type="checkbox" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} />
        {t("bundles.with_files")}
      </label>
      <label className="chk">
        <input
          type="checkbox"
          checked={withPacks && !anthology}
          disabled={anthology}
          aria-describedby={anthology ? "packs-note" : undefined}
          onChange={(e) => setWithPacks(e.target.checked)}
        />
        {t("bundles.with_packs")}
      </label>
      {anthology && (
        <p className="muted" id="packs-note">
          {t("bundles.with_packs_anthology")}
        </p>
      )}
      {err && (
        <p className="fielderr" role="alert">
          {err}
        </p>
      )}
      <div className="editor__foot">
        <Button type="submit" className="pillbtn" isDisabled={busy}>
          {busy ? t("bundles.building") : t("bundles.build")}
        </Button>
      </div>
    </form>
  );
}
