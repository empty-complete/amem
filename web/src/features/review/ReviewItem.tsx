import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { agentName } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { type LangString, pickText, useText } from "../../ui/lang";
import { RegionState } from "../../ui/RegionState";
import { StatusText } from "../../ui/StatusText";
import { Body } from "../record/Body";
import { type Content, RecordContent } from "../record/Content";
import { Properties } from "../record/Properties";
import { kindLabel, recordPath } from "../records/RecordList";
import { Sky } from "../sky/Sky";
import { SourcePanel } from "../source/SourcePanel";
import { DiffFields } from "./DiffFields";
import { fieldDiff, wordDiff } from "./diff";
import { REASON_ICON } from "./reasons";

type View = components["schemas"]["ReviewItemView"];
// details пункта в форме ядра (check._details): issues — коды замечаний, risk — коды риска, candidates —
// похожие записи уровней 3–4. Замечание объектом с текстом тоже понимаем (пункт, поставленный вручную).
type IssueObj = {
  code?: string;
  severity?: "violation" | "warning" | "info";
  message?: string;
  path?: string;
};
type Issue = string | IssueObj;
type Candidate = { code: string; ref: string; score?: number };
const SEV: Record<NonNullable<IssueObj["severity"]>, "bad" | "wait" | "quiet"> = {
  violation: "bad",
  warning: "wait",
  info: "quiet",
};
const REF = /^(atm|ent):/;

/** Код ядра словами: известные — из перевода, прочие — сам код без подчёркиваний. */
function useCodeText() {
  const { t } = useTranslation();
  return (code: string) => t(`review.code.${code}`, { defaultValue: code.replaceAll("_", " ") });
}

/** Похожая запись: ссылка с подписью; имя из той же пачки (@имя) — текстом, его не открыть. */
function CandidateRow({ c }: { c: Candidate }) {
  const word = useCodeText();
  const { text } = useText();
  const rec = useQuery({ ...q.record(c.ref), enabled: REF.test(c.ref) });
  const label = text((rec.data?.payload as { label?: LangString } | undefined)?.label) || c.ref;
  return (
    <li>
      <span className="status" data-tone={c.code === "related" ? "quiet" : "wait"}>
        <Icon name={c.code === "related" ? "link" : "warn"} />
      </span>
      {word(c.code)}: {REF.test(c.ref) ? <Link {...recordPath(c.ref)}>{label}</Link> : label}
    </li>
  );
}

function Diff({ v }: { v: View }) {
  const { t, i18n } = useTranslation();
  const cur = (v.current as { payload?: Record<string, unknown> } | null)?.payload ?? {};
  const prop = v.proposed as { payload?: Record<string, unknown>; agent?: string } | null;
  const changes = fieldDiff(cur, prop?.payload ?? {});
  return (
    <section className="widget" aria-label={t("review.diff")}>
      <h2>
        {t("review.diff")}
        {prop?.agent && (
          <span className="muted">
            {" "}
            · {t("review.diff_by", { who: agentName(prop.agent, i18n.language) })}
          </span>
        )}
      </h2>
      <DiffFields changes={changes} />
    </section>
  );
}

function Versions({ v }: { v: View }) {
  const { t } = useTranslation();
  const ver = v.versions as {
    object_name?: string;
    page?: string;
    old: { version: number; text: string };
    new: { version: number; text: string };
  } | null;
  if (!ver) return null;
  const pieces = wordDiff(ver.old.text, ver.new.text);
  return (
    <section className="widget" aria-label={t("review.versions")}>
      <h2>
        {t("review.versions")}
        {ver.object_name && (
          <span className="muted">
            {" "}
            · {ver.object_name}
            {ver.page ? `, ${t("source.page", { n: ver.page })}` : ""}
          </span>
        )}
      </h2>
      <div className="vers">
        <figure>
          <figcaption>{t("review.old", { n: ver.old.version })}</figcaption>
          <blockquote className="quote diff">
            {pieces
              .filter((x) => x.op !== "add")
              .map((x, i) =>
                x.op === "del" ? (
                  // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                  <del key={i}>{x.text}</del>
                ) : (
                  // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                  <span key={i}>{x.text}</span>
                ),
              )}
          </blockquote>
        </figure>
        <figure>
          <figcaption>{t("review.new", { n: ver.new.version })}</figcaption>
          <blockquote className="quote diff">
            {pieces
              .filter((x) => x.op !== "del")
              .map((x, i) =>
                x.op === "add" ? (
                  // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                  <ins key={i}>{x.text}</ins>
                ) : (
                  // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                  <span key={i}>{x.text}</span>
                ),
              )}
          </blockquote>
        </figure>
      </div>
    </section>
  );
}

/** Пункт проверки (разд. 5.7): что спрошено, утверждение с источником, замечания, сравнение, версии, вердикт модели. */
export function ReviewItemPane({ id, onBack }: { id: string; onBack?: () => void }) {
  const { t, i18n } = useTranslation();
  const word = useCodeText();
  const v = useQuery(q.reviewItem(id));
  const vocab = useQuery(q.vocab("kind"));
  const [active, setActive] = useState(0);
  if (v.isPending) return <RegionState state="loading" />;
  if (v.isError)
    return (
      <RegionState
        state="error"
        message={errorText(v.error, t("region.offline"))}
        retry={() => v.refetch()}
      />
    );
  const { item, record } = v.data;
  const d = (item.details ?? {}) as {
    issues?: Issue[];
    risk?: string[];
    candidates?: Candidate[];
    verdict?: string;
    confidence?: number;
    note?: string;
    model?: string;
  };
  const p = record.payload as {
    kind?: string;
    label?: LangString;
    summary_plain?: LangString;
    body?: LangString;
    basis?: string;
  };
  const kind = p.kind ?? "";
  return (
    <article className="ritem" aria-labelledby="ritem-title">
      {onBack && (
        <button type="button" className="navlink ritem__back" onClick={onBack}>
          ← {t("review.back")}
        </button>
      )}
      <p className="ritem__q">
        <Icon name={REASON_ICON[item.reason]} />
        {t(`review.q.${item.reason}`)}
      </p>
      <div className="ritem__head">
        <h1 id="ritem-title" className="title">
          <Link {...recordPath(record.ref)}>{pickText(p.label, i18n.language) || item.label}</Link>
        </h1>
        <StatusText status={record.status} />
      </div>
      <p className="muted">
        {t("review.by", {
          who: agentName(item.author ?? record.agent, i18n.language),
          when: new Date(item.created_at).toLocaleString(i18n.language),
        })}
      </p>

      {item.reason === "semantic_doubt" && d.verdict && (
        <section className="widget verdict" aria-label={t("review.verdict")}>
          <h2>{t("review.verdict")}</h2>
          <p>
            <strong>{t(`review.verdict_v.${d.verdict}`, { defaultValue: d.verdict })}</strong>
            {d.confidence != null && (
              <span className="muted">
                {" "}
                · {t("review.confidence", { n: Math.round(d.confidence * 100) })}
              </span>
            )}
            {d.model && <span className="muted"> · {agentName(d.model, i18n.language)}</span>}
          </p>
          {d.note && <p>{d.note}</p>}
        </section>
      )}
      {!!(d.issues?.length || d.risk?.length || d.candidates?.length) && (
        <section className="widget" aria-label={t("review.issues")}>
          <h2>{t("review.issues")}</h2>
          <ul className="issues">
            {(d.risk ?? []).map((r) => (
              <li key={`risk-${r}`}>
                <span className="status" data-tone="wait">
                  <Icon name="shield" />
                </span>
                {t("review.risk", { what: word(r) })}
              </li>
            ))}
            {(d.issues ?? [])
              // код кандидата показывает строка кандидата ниже — с самой похожей записью
              .filter((i) => typeof i !== "string" || !d.candidates?.some((c) => c.code === i))
              .map((i) => {
                const o: IssueObj = typeof i === "string" ? { code: i } : i;
                const sev = o.severity ?? "warning";
                return (
                  <li key={`${o.code}-${o.path}-${o.message}`}>
                    <span className="status" data-tone={SEV[sev]}>
                      <Icon name={sev === "info" ? "dash" : "warn"} />
                    </span>
                    {o.message ?? word(o.code ?? "")}
                  </li>
                );
              })}
            {(d.candidates ?? []).map((c) => (
              <CandidateRow key={`${c.code}-${c.ref}`} c={c} />
            ))}
          </ul>
        </section>
      )}
      {item.reason === "edit" && v.data.proposed && <Diff v={v.data} />}
      {item.reason === "source_changed" && <Versions v={v.data} />}

      <Properties view={record} kindLabel={kindLabel(vocab.data, kind, i18n.language)} />
      {p.summary_plain && <p className="lede">{pickText(p.summary_plain, i18n.language)}</p>}
      <RecordContent content={(record.payload as { content?: Content }).content} />
      {p.body && (
        <Body text={pickText(p.body, i18n.language)} target={(l) => ({ to: "/search", search: { q: l } })} />
      )}
      {(record.sources.length > 0 || p.basis) && (
        <div className="ritem__src">
          <SourcePanel sources={record.sources} basis={p.basis} active={active} onActive={setActive} />
        </div>
      )}
      <section className="widget" aria-label={t("review.sky")}>
        <h2>{t("review.sky")}</h2>
        <Sky centerRef={record.ref} height={340} />
      </section>
    </article>
  );
}
