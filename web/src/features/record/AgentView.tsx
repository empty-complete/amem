import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { stringify } from "yaml";
import type { components } from "../../api/schema";
import { useCopy } from "../../ui/useCopy";

type View = components["schemas"]["RecordView"];

/** Что получает агент: запись amem.atom/1 как есть, без украшений интерфейса. */
export function agentBody(v: View) {
  return {
    ref: v.ref,
    revision: v.revision,
    status: v.status,
    review_state: v.review_state,
    recorded_at: v.recorded_at,
    agent: v.agent,
    payload: v.payload,
    sources: v.sources.map(({ object, object_version, selectors, quote, verdict, role }) => ({
      object,
      object_version,
      selectors,
      quote,
      verdict,
      role,
    })),
  };
}

export function AgentView({ view }: { view: View }) {
  const { t } = useTranslation();
  const { copy, message } = useCopy(t("record.copy_failed"));
  const body = agentBody(view);
  return (
    <section className="agentview" aria-label={t("record.agent_view")}>
      <div className="agentview__bar">
        <span className="muted">{t("record.agent_view")}</span>
        <Button
          size="sm"
          variant="ghost"
          onPress={() => copy(JSON.stringify(body, null, 2), t("record.copied"))}
        >
          {t("record.copy_json")}
        </Button>
        <span role="status" aria-live="polite" className="muted">
          {message}
        </span>
      </div>
      <pre>{stringify(body, { lineWidth: 0 })}</pre>
    </section>
  );
}
