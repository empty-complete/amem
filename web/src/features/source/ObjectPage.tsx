import { Button } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { lazy, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { type ApiError, errorText } from "../../api/errors";
import { contentUrl, q } from "../../api/queries";
import type { components } from "../../api/schema";
import { formatDate, formatSize } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { KindChip } from "../../ui/KindChip";
import { type LangString, pickText } from "../../ui/lang";
import { RegionState } from "../../ui/RegionState";
import { useCopy } from "../../ui/useCopy";
import { Body } from "../record/Body";
import "../record/record.css";
import { recordPath } from "../records/RecordList";
import { type CitedRange, SheetPreview } from "./SheetPreview";
import { fileType, placeText, VerdictText } from "./SourcePanel";
import "./source.css";

const PdfPage = lazy(() => import("./PdfPage"));

type Obj = components["schemas"]["ObjectView"];
type Cite = components["schemas"]["ObjectCitation"];
type Selector = { type: string; value?: string; label?: string };
const sels = (c: Cite) => c.selectors as unknown as Selector[];

/** Что в файле ещё не разобрано: листы и страницы без цитат, если разбор частичный. */
export function unparsed(o: Obj, pageWord: (n: number) => string): string[] {
  if (o.status !== "partial") return [];
  const cited = o.cited_by ?? [];
  if (o.sheets?.length) {
    const used = new Set(
      cited.flatMap((c) =>
        sels(c)
          .filter((s) => s.type === "sheet")
          .map((s) => s.value),
      ),
    );
    return o.sheets.filter((s) => !used.has(s));
  }
  if (o.pages) {
    const used = new Set(
      cited.flatMap((c) =>
        sels(c)
          .filter((s) => s.type === "page")
          .map((s) => Number(s.value)),
      ),
    );
    return Array.from({ length: o.pages }, (_, i) => i + 1)
      .filter((n) => !used.has(n))
      .map(pageWord);
  }
  return [];
}

/** «Попросить агента» разобрать то, что не разобрано: задача через POST /tasks; агенты берут её через MCP. */
function AskAgent({ object, version, what }: { object: string; version: number; what: string[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const tasks = useQuery(q.tasks(object));
  const busy = tasks.data?.some((x) => x.state === "open" || x.state === "claimed");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        isDisabled={busy}
        onPress={async () => {
          try {
            await api.POST("/tasks", { body: { kind: "parse", object, version, note: what.join(", ") } });
            setMsg(t("source.task_set"));
            qc.invalidateQueries({ queryKey: ["tasks", object] });
          } catch (e) {
            setMsg((e as ApiError).detail ?? (e as ApiError).title);
          }
        }}
      >
        {busy ? t("source.task_open") : t("source.ask_agent")}
      </Button>
      <span role="status" className="muted">
        {msg}
      </span>
    </>
  );
}

function Brief({ objectId }: { objectId: string }) {
  const notes = useQuery(q.about(`obj:${objectId}`));
  // бриф — заметка, которая ссылается на файл как на источник (about у атома ведёт только на сущности)
  const first = notes.data?.items.find((r) => r.kind_or_class === "note");
  const rec = useQuery({ ...q.record(first?.ref ?? ""), enabled: !!first });
  const { t, i18n } = useTranslation();
  const p = rec.data?.payload as { summary_plain?: LangString; body?: LangString } | undefined;
  if (!p) return null;
  const md = [pickText(p.summary_plain, i18n.language), pickText(p.body, i18n.language)]
    .filter(Boolean)
    .join("\n\n");
  return (
    <section className="widget" aria-label={t("source.brief")}>
      <h2>{t("source.brief")}</h2>
      <Body text={md} target={(l) => ({ to: "/search", search: { q: l } })} />
      {first && (
        <Link className="muted" {...recordPath(first.ref)}>
          {first.label}
        </Link>
      )}
    </section>
  );
}

function ObjectView_({ o }: { o: Obj }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { copy, message } = useCopy(t("record.copy_failed"));
  const last = o.versions[o.versions.length - 1];
  const path = o.logical_paths?.[0] ?? o.url ?? null;
  const cited = o.cited_by ?? [];
  const ranges: CitedRange[] = useMemo(
    () =>
      cited.flatMap((c) => {
        const sheet = sels(c).find((s) => s.type === "sheet")?.value;
        const range = sels(c).find((s) => s.type === "range")?.value;
        return sheet && range ? [{ sheet, range, label: c.record.label }] : [];
      }),
    [cited],
  );
  const pageQuotes = useMemo(() => {
    const first = sels(cited[0] ?? ({ selectors: [] } as never)).find((s) => s.type === "page");
    const n = Number(first?.value ?? 1);
    return {
      page: n,
      quotes: cited
        .filter((c) => sels(c).some((s) => s.type === "page" && Number(s.value) === n))
        .flatMap((c) => (c.quote ? [c.quote] : [])),
    };
  }, [cited]);
  const rest = unparsed(o, (n) => t("source.page", { n }));
  const name = o.original_name ?? o.url ?? o.id;

  return (
    <article className="note objpage" aria-labelledby="obj-title">
      <div className="note__bar">
        <span className="ft" aria-hidden="true">
          {fileType(o, lang)}
        </span>
        <span className="crumbs">{t("source.panel")}</span>
      </div>
      <h1 id="obj-title" className="title">
        {name.replace(/_/g, " ").replace(/\.[a-z0-9]+$/i, "")}
      </h1>

      <dl className="props" aria-label={t("source.props")}>
        <div className="prop">
          <dt className="k">
            <Icon name="file" size={14} />
            <span>{t("record.p_kind")}</span>
          </dt>
          <dd className="v">
            {fileType(o, lang)}
            {o.status && <span className="muted">· {t(`source.status.${o.status}`)}</span>}
          </dd>
        </div>
        {path && (
          <div className="prop">
            <dt className="k">
              <Icon name="folder" size={14} />
              <span>{t("source.path")}</span>
            </dt>
            <dd className="v">
              <code className="code">{path}</code>
              <Button size="sm" variant="ghost" onPress={() => copy(path, t("source.path_copied"))}>
                <Icon name="copy" />
                {t("source.copy_path")}
              </Button>
              <span role="status" aria-live="polite" className="muted">
                {message}
              </span>
            </dd>
          </div>
        )}
        {last && (
          <div className="prop">
            <dt className="k">
              <Icon name="history" size={14} />
              <span>{t("source.versions")}</span>
            </dt>
            <dd className="v">
              {t("source.v_line", {
                n: last.n,
                date: formatDate(last.recorded_at, lang),
                size: formatSize(last.size, lang),
              })}
            </dd>
          </div>
        )}
        {(o.sheets?.length || o.pages) && (
          <div className="prop">
            <dt className="k">
              <Icon name="stack" size={14} />
              <span>{o.sheets?.length ? t("source.sheets") : t("source.pages")}</span>
            </dt>
            <dd className="v">{o.sheets?.length ? o.sheets.join(", ") : o.pages}</dd>
          </div>
        )}
      </dl>

      <Brief objectId={o.id} />

      <section className="widget" aria-label={t("source.preview")}>
        <h2>{t("source.preview")}</h2>
        {last && o.media_type === "application/pdf" ? (
          <Suspense fallback={<RegionState state="loading" />}>
            <div className="objpdf">
              <PdfPage url={contentUrl(o.id, last.n)} page={pageQuotes.page} quotes={pageQuotes.quotes} />
            </div>
          </Suspense>
        ) : last && o.sheets?.length ? (
          <SheetPreview id={o.id} version={last.n} sheets={o.sheets} cited={ranges} />
        ) : last && o.media_type?.startsWith("image/") ? (
          <img className="objimg" src={contentUrl(o.id, last.n)} alt={name} />
        ) : (
          <p className="muted">{t("source.no_preview")}</p>
        )}
      </section>

      <div className="widgets">
        <section className="widget" aria-label={t("source.cited_by")}>
          <h2>{t("source.cited_by")}</h2>
          <ul className="cites">
            {cited.map((c) => (
              <li key={`${c.record.ref}-${JSON.stringify(c.selectors)}`}>
                <Link {...recordPath(c.record.ref)} className="cite">
                  {c.record.kind && <KindChip kind={c.record.kind} />}
                  <span className="cite__main">
                    <span>{c.record.label}</span>
                    <span className="muted">
                      {placeText(c.selectors, t)}
                      {c.quote ? ` · «${c.quote}»` : ""}
                    </span>
                  </span>
                  <VerdictText verdict={c.verdict} />
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="widget" aria-label={t("source.versions")}>
          <h2>{t("source.versions")}</h2>
          <ol className="hist">
            {[...o.versions].reverse().map((v) => (
              <li key={v.n}>
                <time dateTime={v.recorded_at}>{formatDate(v.recorded_at, lang)}</time>
                <span>
                  {t("source.version", { n: v.n })}
                  {v.size != null && ` · ${formatSize(v.size, lang)}`}
                </span>
                <span className="muted">{v.cited_by ? t("source.v_cited", { count: v.cited_by }) : ""}</span>
              </li>
            ))}
          </ol>
        </section>

        {o.status === "partial" && (
          <section className="widget" aria-label={t("source.unparsed")}>
            <h2>{t("source.unparsed")}</h2>
            {rest.length ? (
              <div className="rels">
                {rest.map((r) => (
                  <span key={r} className="pill">
                    {r}
                  </span>
                ))}
                <AskAgent object={o.id} version={last?.n ?? 1} what={rest} />
              </div>
            ) : (
              <p className="muted">{t("source.nothing_unparsed")}</p>
            )}
          </section>
        )}
      </div>
      {last && (
        <footer className="foot">
          <a className="navlink" href={contentUrl(o.id, last.n)} target="_blank" rel="noreferrer">
            <Icon name="external" />
            {t("source.open_file")}
          </a>
          <span className="spacer" />
          <code className="ref">{o.id}</code>
        </footer>
      )}
    </article>
  );
}

/** Страница источника (разд. 5.12): свойства и путь, превью с цитатами, кто ссылается, версии, что не разобрано. */
export function ObjectPage({ objectId }: { objectId: string }) {
  const { t } = useTranslation();
  const o = useQuery(q.object(objectId));
  if (o.isPending) return <RegionState state="loading" />;
  if (o.isError)
    return (
      <RegionState
        state="error"
        message={errorText(o.error, t("region.offline"))}
        retry={() => o.refetch()}
      />
    );
  return <ObjectView_ o={o.data} />;
}
