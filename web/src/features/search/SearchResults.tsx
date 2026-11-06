import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { Highlight } from "../../ui/Highlight";
import { KindChip } from "../../ui/KindChip";
import { RegionState } from "../../ui/RegionState";
import { StatusText } from "../../ui/StatusText";
import { kindLabel, recordPath } from "../records/RecordList";
import "../records/records.css";
import type { SearchParams } from "./params";

const KINDS = ["parameter", "fact", "decision", "question", "lesson", "note"];

/** Результаты exact_fact: точное совпадение кода первым, смысловой канал честно назван, фильтры в URL. */
export function SearchResults({ params }: { params: SearchParams }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const res = useQuery(q.search(params));
  const vocab = useQuery(q.vocab("kind"));
  const set = (patch: Partial<SearchParams>) => navigate({ to: "/search", search: { ...params, ...patch } });
  const toggleKind = (k: string) =>
    set({ kind: params.kind.includes(k) ? params.kind.filter((x) => x !== k) : [...params.kind, k] });

  if (!params.q.trim()) return <RegionState state="empty" text={t("search.prompt")} />;
  return (
    <section aria-labelledby="search-title">
      <div className="page-head">
        <h1 id="search-title">{t("search.title", { q: params.q })}</h1>
        {res.data && <span className="count">{t("search.found", { count: res.data.candidate_count })}</span>}
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: a row of toggle buttons, not a form fieldset */}
      <div className="filters" role="group" aria-label={t("search.kind")}>
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            className="chipbtn"
            aria-pressed={params.kind.includes(k)}
            onClick={() => toggleKind(k)}
          >
            {kindLabel(vocab.data, k, i18n.language)}
          </button>
        ))}
      </div>
      {res.data?.semantic === "unavailable" && <p className="note-line">{t("search.semanticOff")}</p>}
      {res.isPending ? (
        <RegionState state="loading" />
      ) : res.isError ? (
        <RegionState
          state="error"
          message={errorText(res.error, t("region.offline"))}
          retry={() => res.refetch()}
        />
      ) : res.data.items.length === 0 ? (
        <RegionState state="empty" text={t("search.nothing", { q: params.q })} />
      ) : (
        <>
          <ul className="rows">
            {res.data.items.map((h) => {
              const exact = h.matches.some((m) => m.channel === "code_exact");
              return (
                <li key={h.ref}>
                  <Link className="row" {...recordPath(h.ref)}>
                    <span className="main">
                      <span className="line1">
                        {h.kind && (
                          <KindChip kind={h.kind} label={kindLabel(vocab.data, h.kind, i18n.language)} />
                        )}
                        <span className="ttl">{h.label ?? h.ref}</span>
                      </span>
                      <span className="line2">
                        {exact && <span className="exact">{t("search.exactCode")}</span>}
                        {h.about?.map((a) => (
                          <span key={a.ref}>{a.label}</span>
                        ))}
                        <span className="snip">
                          <Highlight text={h.snippet} query={params.q} />
                        </span>
                      </span>
                    </span>
                    <span className="side">
                      <StatusText status={h.status} />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {res.data.candidate_count > res.data.items.length && params.limit < 100 && (
            <div className="more">
              <Button
                variant="secondary"
                size="sm"
                onPress={() => set({ limit: Math.min(100, params.limit + 20) })}
              >
                {t("search.more")}
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
