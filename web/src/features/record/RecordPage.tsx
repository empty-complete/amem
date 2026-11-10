import { Button, Dropdown, Label } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { agentName, formatDate } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { pickText } from "../../ui/lang";
import { RegionState } from "../../ui/RegionState";
import { StatusText } from "../../ui/StatusText";
import { useCopy } from "../../ui/useCopy";
import { kindLabel, recordPath } from "../records/RecordList";
import { Sky } from "../sky/Sky";
import { SourcePanel } from "../source/SourcePanel";
import { draftKey, loadDraft } from "../write/drafts";
import { MoveDialog } from "../write/MoveDialog";
import { type Draft, type FieldIssues, fromPayload } from "../write/proposal";
import { RecordEditor } from "../write/RecordEditor";
import { AgentView } from "./AgentView";
import { Body, type WikiTarget } from "./Body";
import { type Content, RecordContent } from "./Content";
import { recordToDocument } from "./doc";
import { type Payload, Properties, valueLine } from "./Properties";
import { HistoryWidget, LinksWidget, SimilarWidget, SourcesWidget } from "./Widgets";
import "./record.css";

const SourceView = lazy(() => import("./SourceView"));

type View = components["schemas"]["RecordView"];
export type RecordMode = "human" | "source" | "agent";

function Crumbs({ view }: { view: View }) {
  const { t } = useTranslation();
  const chain = [...(view.ancestors ?? []), ...(view.about ?? []).slice(0, 1)];
  if (!chain.length) return <span />;
  return (
    <nav className="crumbs" aria-label={t("record.about")}>
      {chain.map((c, i) => (
        <span key={c.ref}>
          {i > 0 && <span aria-hidden="true"> / </span>}
          <Link {...recordPath(c.ref)}>{c.label}</Link>
        </span>
      ))}
    </nav>
  );
}

function Note({ view, mode }: { view: View; mode: RecordMode }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const navigate = useNavigate();
  const p = view.payload as unknown as Payload;
  const vocab = useQuery(q.vocab(view.target === "entity" ? "entity_class" : "kind"));
  const links = useQuery(q.links(view.ref));
  const [active, setActive] = useState(0);
  const session = useQuery(q.session());
  const own = !!session.data && session.data.agent === view.agent && view.agent.startsWith("person:");
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [moving, setMoving] = useState(false);
  const [rejected, setRejected] = useState<{ draft: Draft; issues: FieldIssues } | null>(null);
  const templates = useQuery({ ...q.templates(view.target), enabled: own });
  const kindCode = String(
    (view.payload as { kind?: string; entity_class?: string }).kind ??
      (view.payload as { entity_class?: string }).entity_class ??
      "",
  );
  const tpl = templates.data?.find((x) => x.code === kindCode);
  const editKey = draftKey("edit", view.ref);
  useEffect(() => {
    if (!own) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyE") {
        e.preventDefault();
        setEditing((x) => !x);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [own]);
  const { copy, message } = useCopy(t("record.copy_failed"));
  const doc = useMemo(() => recordToDocument(p, view.about, view.sources as never, lang), [p, view, lang]);
  const kind = p.kind ?? p.entity_class ?? "";
  const label = pickText(p.label, lang);
  const main = p.content?.values?.[0];

  const target = useCallback(
    (l: string): WikiTarget => {
      const hit =
        links.data?.find((x) => x.other.label === l)?.other ?? view.about?.find((a) => a.label === l) ?? null;
      return hit ? recordPath(hit.ref) : { to: "/search", search: { q: l } };
    },
    [links.data, view.about],
  );
  const setMode = (m: RecordMode) =>
    navigate({
      to: ".",
      search: (s: object) => ({ ...s, view: m === "human" ? undefined : m }) as never,
      replace: true,
    });

  const pending = view.open_items.find((i) => i.state === "queued" || i.state === "claimed");
  const summary = pickText(p.summary_plain ?? p.description, lang);
  const body = pickText(p.body, lang);

  return (
    <div className="recpage">
      <article className="note" aria-labelledby="rec-title">
        <div className="note__bar">
          <Crumbs view={view} />
          <StatusText status={view.status} />
          <span className="modes">
            {own ? (
              <Button
                isIconOnly
                size="sm"
                variant="ghost"
                aria-label={t("edit.edit")}
                aria-pressed={editing}
                onPress={() => setEditing((e) => !e)}
              >
                <Icon name="pencil" />
              </Button>
            ) : (
              <Dropdown>
                <Button
                  isIconOnly
                  size="sm"
                  variant="ghost"
                  aria-label={t("edit.not_own", { who: agentName(view.agent, lang) })}
                >
                  <Icon name="pencil" />
                </Button>
                <Dropdown.Popover>
                  <Dropdown.Menu
                    onAction={async (key) => {
                      if (key === "enqueue") {
                        await api.POST("/review/enqueue", { body: { ref: view.ref, reason: "audit" } });
                        setNote(t("edit.enqueued"));
                      }
                      if (key === "beside")
                        navigate({
                          to: "/new",
                          search: { about: view.about?.[0]?.ref, related: view.ref } as never,
                        });
                    }}
                  >
                    <Dropdown.Item id="enqueue" textValue={t("edit.enqueue")}>
                      <Label>{t("edit.enqueue")}</Label>
                    </Dropdown.Item>
                    <Dropdown.Item id="beside" textValue={t("edit.beside")}>
                      <Label>{t("edit.beside")}</Label>
                    </Dropdown.Item>
                  </Dropdown.Menu>
                </Dropdown.Popover>
              </Dropdown>
            )}
            <Button
              isIconOnly
              size="sm"
              variant="ghost"
              aria-label={t("record.mode_source")}
              aria-pressed={mode === "source"}
              onPress={() => setMode(mode === "source" ? "human" : "source")}
            >
              <Icon name="code" />
            </Button>
            <Dropdown>
              <Button isIconOnly size="sm" variant="ghost" aria-label={t("record.more")}>
                <Icon name="more" />
              </Button>
              <Dropdown.Popover>
                <Dropdown.Menu
                  onAction={(key) => {
                    if (key === "agent") setMode(mode === "agent" ? "human" : "agent");
                    if (key === "ref") copy(view.ref, t("record.copied"));
                    if (key === "md") copy(doc, t("record.copied"));
                    if (key === "move") setMoving(true);
                  }}
                >
                  <Dropdown.Item id="agent" textValue={t("record.mode_agent")}>
                    <Label>{mode === "agent" ? t("record.mode_human") : t("record.mode_agent")}</Label>
                  </Dropdown.Item>
                  <Dropdown.Item id="ref" textValue={t("record.copy_ref")}>
                    <Label>{t("record.copy_ref")}</Label>
                  </Dropdown.Item>
                  <Dropdown.Item id="md" textValue={t("record.copy_md")}>
                    <Label>{t("record.copy_md")}</Label>
                  </Dropdown.Item>
                  <Dropdown.Item id="move" textValue={t("folders.move_to")}>
                    <Label>{t("folders.move_to")}</Label>
                  </Dropdown.Item>
                </Dropdown.Menu>
              </Dropdown.Popover>
            </Dropdown>
          </span>
        </div>
        <span role="status" aria-live="polite" className={note ? "note__status" : "sr-only"}>
          {note || message}
        </span>

        {editing && templates.data ? (
          <RecordEditor
            key={`${view.ref}-${view.revision}`}
            initial={
              rejected?.draft ?? loadDraft(editKey) ?? fromPayload(view.payload as never, tpl, view.target)
            }
            labels={Object.fromEntries((view.about ?? []).map((a) => [a.ref, a.label]))}
            recordId={view.ref}
            base={view.payload as never}
            draftKey={editKey}
            issues={rejected?.issues}
            onQueued={() => {
              setRejected(null);
              setEditing(false);
            }}
            onCancel={() => {
              setRejected(null);
              setEditing(false);
            }}
            onRejected={(draft, issues) => {
              setRejected({ draft, issues });
              setEditing(true);
            }}
          />
        ) : (
          <>
            <h1 id="rec-title" className="title">
              {label}
            </h1>
            {pending && (
              <p className="pending">
                <Icon name="clock" />
                {t("record.pending", {
                  what:
                    (pending.details as { note?: string } | null)?.note ??
                    t(`record.reason.${pending.reason}`),
                })}
              </p>
            )}

            {mode === "source" ? (
              <Suspense fallback={<RegionState state="loading" />}>
                <SourceView doc={doc} label={t("record.source_view")} />
              </Suspense>
            ) : mode === "agent" ? (
              <AgentView view={view} />
            ) : (
              <>
                <Properties view={view} kindLabel={kindLabel(vocab.data, kind, lang)} />
                {main && kind === "parameter" && <p className="bigvalue">{valueLine(main, lang)}</p>}
                {summary && <p className="lede">{summary}</p>}
                <RecordContent content={p.content as Content | undefined} />
                {body ? (
                  <Body text={body} target={target} />
                ) : (
                  !summary && <p className="muted">{t("record.no_body")}</p>
                )}
                <div className="widgets">
                  <SourcesWidget sources={view.sources} active={active} onActive={setActive} />
                  <LinksWidget recordRef={view.ref} />
                  <section className="widget" aria-label={t("sky.widget")}>
                    <h2>{t("sky.widget")}</h2>
                    <Sky centerRef={view.ref} height={340} />
                  </section>
                  <HistoryWidget recordRef={view.ref} />
                  <SimilarWidget recordRef={view.ref} />
                </div>
              </>
            )}
          </>
        )}

        <MoveDialog
          recordRef={view.ref}
          current={view.folder ?? null}
          open={moving}
          onClose={() => setMoving(false)}
        />
        <footer className="foot">
          <span>
            {agentName(view.agent, lang)} · {formatDate(view.recorded_at, lang)}
          </span>
          <span>{t("record.foot", { revision: view.revision })}</span>
          <span className="spacer" />
          <code className="ref">{view.ref}</code>
        </footer>
      </article>
      <SourcePanel sources={view.sources} basis={p.basis} active={active} onActive={setActive} />
    </div>
  );
}

/** Экран записи как заметки (разд. 5.4): путь, свойства, тело, источники, связи; справа — источник с цитатой. */
export function RecordPage({ recordRef, view = "human" }: { recordRef: string; view?: RecordMode }) {
  const { t } = useTranslation();
  const rec = useQuery(q.record(recordRef));
  if (rec.isPending) return <RegionState state="loading" />;
  if (rec.isError) {
    return (
      <RegionState
        state="error"
        message={errorText(rec.error, t("region.offline"))}
        retry={() => rec.refetch()}
      />
    );
  }
  return <Note key={rec.data.ref} view={rec.data} mode={view} />;
}
