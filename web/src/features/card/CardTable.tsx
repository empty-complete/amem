import { Button } from "@heroui/react";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatValue, type ValueLike } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { recordPath } from "../records/RecordList";
import type { CardField } from "./card";

type Candidate = { value?: ValueLike; atom?: string; quote?: string; source?: string };
type Src = { label?: string };

function Sub({ f }: { f: CardField }) {
  const { t } = useTranslation();
  const src = (f.sources as Src[] | undefined)?.[0]?.label;
  if (f.inherited_from) return <>{t("card.inherited", { from: f.inherited_from })}</>;
  if (f.state === "conflict") return <>{t("card.waits")}</>;
  if (f.state === "asked" && f.ask) return <>{t("card.you_asked", { ask: f.ask })}</>;
  if (f.state === "missing" && f.hint) return <>{t("card.where", { hint: f.hint })}</>;
  return src ? <>{src}</> : null;
}

function Value({ f, open, toggle }: { f: CardField; open: boolean; toggle: () => void }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  switch (f.state) {
    case "known":
      return (
        <span className="cval">
          <span className="num">{formatValue(f.value as ValueLike, lang)}</span>
          <span className="status" data-tone="ok">
            <Icon name="check" />
            <span className="sr-only">{t("card.known")}</span>
          </span>
        </span>
      );
    case "conflict":
      return (
        <Button size="sm" variant="ghost" onPress={toggle} aria-expanded={open} className="cval">
          <span className="status" data-tone="wait">
            <Icon name="warn" />
            {t("card.conflict", { count: f.candidates?.length ?? 2 })}
          </span>
        </Button>
      );
    case "asked":
      return (
        <span className="status" data-tone="wait">
          <Icon name="clock" />
          {t("card.asked")}
        </span>
      );
    case "na":
      return <span className="muted">{t("card.na")}</span>;
    default:
      return (
        <span className="cval">
          {f.default && (
            <span className="muted">
              {t("card.default", { value: formatValue(f.default as ValueLike, lang) })}
            </span>
          )}
          {f.required ? (
            <span className="need">{t("card.need")}</span>
          ) : (
            !f.default && <span className="muted">{t("card.missing")}</span>
          )}
        </span>
      );
  }
}

function Row({ f }: { f: CardField }) {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const atom = f.atoms?.[0];
  return (
    <li className="crow" data-state={f.state}>
      <span className="crow__name">
        {atom ? <Link {...recordPath(atom)}>{f.label ?? f.property}</Link> : (f.label ?? f.property)}
        <span className="crow__sub">
          <Sub f={f} />
        </span>
      </span>
      <Value f={f} open={open} toggle={() => setOpen((o) => !o)} />
      {f.state === "conflict" && open && (
        <ul className="cands" aria-label={t("card.candidates")}>
          {(f.candidates as Candidate[]).map((c) => (
            <li key={`${c.atom}-${c.source}`}>
              <strong className="num">{formatValue(c.value, i18n.language)}</strong>
              {c.quote && <q>{c.quote}</q>}
              <span className="muted">
                {c.atom ? <Link {...recordPath(c.atom)}>{c.source}</Link> : c.source}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Карточка профиля сгруппированными списками: имя, где взято, значение и состояние словом. */
export function CardTable({ groups }: { groups: { name: string | null; fields: CardField[] }[] }) {
  const { t } = useTranslation();
  return (
    <div className="ctable">
      {groups.map((g) => (
        <section key={g.name ?? "-"} aria-label={g.name ?? t("card.other")}>
          <h2>{g.name ?? t("card.other")}</h2>
          <ul>
            {g.fields.map((f) => (
              <Row key={f.property} f={f} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
