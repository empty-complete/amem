import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { components } from "../../api/schema";
import { agentName, formatDate, formatValue, type ValueLike } from "../../ui/format";
import { Icon, type IconName } from "../../ui/icons";
import { type LangString, pickText } from "../../ui/lang";
import { useFamily } from "../../ui/useFamily";
import { recordPath } from "../records/RecordList";

type View = components["schemas"]["RecordView"];
type Value = ValueLike & {
  property: string;
  label?: LangString;
  qualifiers?: (ValueLike & { property: string; label?: LangString })[];
};
export type Payload = {
  kind?: string;
  entity_class?: string;
  label: LangString;
  summary_plain?: LangString;
  description?: LangString;
  body?: LangString;
  content?: { values?: Value[] };
  tags?: string[];
  codes?: string[];
  basis?: string;
  confidence?: number;
  valid_from?: string;
  valid_to?: string;
  qualifiers?: { property: string; label?: LangString; value_text?: string }[];
};

function Row({ icon, name, children }: { icon: IconName; name: string; children: ReactNode }) {
  return (
    <div className="prop">
      <dt className="k">
        <Icon name={icon} size={14} />
        <span>{name}</span>
      </dt>
      <dd className="v">{children}</dd>
    </div>
  );
}

/** Значение параметра одной строкой: «±2 % в диапазоне 10…90 %». */
export function valueLine(v: Value, lang: string) {
  const q = (v.qualifiers ?? []).map((x) => `${pickText(x.label, lang)} ${formatValue(x, lang)}`.trim());
  return [formatValue(v, lang), ...q].filter(Boolean).join(" ");
}

/** Свойства как в Obsidian: значок типа, имя, значение; только заполненные. Технические поля — в «Как видит агент». */
export function Properties({ view, kindLabel }: { view: View; kindLabel: string }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const p = view.payload as unknown as Payload;
  const kind = p.kind ?? p.entity_class ?? "";
  const family = useFamily();
  // «Суть» — свойство, как в Obsidian: строка над остальными, не отдельный абзац
  const summary = pickText(p.summary_plain ?? p.description, lang);
  // значение параметра стоит крупно над текстом — в свойствах только остальные
  const values = (p.content?.values ?? []).slice(kind === "parameter" ? 1 : 0);
  return (
    <dl className="props" aria-label={t("record.props")}>
      <Row icon="stack" name={t("record.p_kind")}>
        <span className="pill kind" data-family={family(kind, view.target)}>
          {kindLabel}
        </span>
      </Row>
      {summary && (
        <Row icon="text" name={t("record.p_summary")}>
          <span className="gist">{summary}</span>
        </Row>
      )}
      {!!view.about?.length && (
        <Row icon="link" name={t("record.p_about")}>
          {view.about.map((a) => (
            <Link key={a.ref} className="pill obj" title={a.label} {...recordPath(a.ref)}>
              <span className="pill__t">{a.label}</span>
            </Link>
          ))}
        </Row>
      )}
      {values.length > 0 && (
        <Row icon="ruler" name={t("record.p_values")}>
          {values.map((v) => (
            <span key={v.property} className="num">
              {pickText(v.label, lang) && <span className="muted">{pickText(v.label, lang)} </span>}
              {valueLine(v, lang)}
            </span>
          ))}
        </Row>
      )}
      {!!p.codes?.length && (
        <Row icon="hash" name={t("record.p_codes")}>
          {p.codes.map((c) => (
            <code key={c} className="code">
              {c}
            </code>
          ))}
        </Row>
      )}
      {(p.valid_from || p.valid_to) && (
        <Row icon="calendar" name={t("record.p_when")}>
          {[p.valid_from && formatDate(p.valid_from, lang), p.valid_to && formatDate(p.valid_to, lang)]
            .filter(Boolean)
            .join(" — ")}
        </Row>
      )}
      {!!p.tags?.length && (
        <Row icon="tag" name={t("record.p_tags")}>
          {p.tags.map((tag) => (
            <Link key={tag} className="pill" to="/search" search={{ q: `#${tag}` } as never}>
              #{tag}
            </Link>
          ))}
        </Row>
      )}
      {p.basis && (
        <Row icon="shield" name={t("record.p_basis")}>
          {t(`record.basis.${p.basis}`, { defaultValue: p.basis })}
        </Row>
      )}
      {(p.qualifiers ?? [])
        .filter((q) => q.value_text)
        .map((q) => (
          <Row key={q.property} icon="dash" name={pickText(q.label, lang) || q.property}>
            {q.value_text}
          </Row>
        ))}
      <Row icon="user" name={t("record.p_by")}>
        {agentName(view.agent, lang)}
        {p.confidence != null && view.agent.startsWith("model:") && (
          <span className="muted">
            {" · "}
            {t("record.p_confidence")} {Math.round(p.confidence * 100)} %
          </span>
        )}
      </Row>
    </dl>
  );
}
