import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { formatValue, unitLabel, type ValueLike } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { recordPath } from "../records/RecordList";
import type { CardField } from "./card";

/** Заполнение карточки на месте (разд. 5.9, п. 3): значение, вопрос или принятое умолчание. */
export interface Fill {
  value: (f: CardField, v: { amount?: number; value_text?: string; unit?: string | null }) => void;
  unknown: (f: CardField) => void;
  accept: (f: CardField) => void;
}

function FillForm({ f, fill, onDone }: { f: CardField; fill: Fill; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const props = useQuery(q.vocab("property"));
  const unit =
    (f.default as ValueLike | null)?.unit ??
    (props.data?.find((p) => p.code === f.property) as { unit?: string } | undefined)?.unit ??
    null;
  const [raw, setRaw] = useState("");
  const save = () => {
    const v = raw.trim();
    if (!v) return;
    const n = Number(v.replace("−", "-").replace(",", "."));
    fill.value(f, Number.isFinite(n) ? { amount: n, unit } : { value_text: v, unit });
    onDone();
  };
  return (
    <div className="fillform">
      <span className="qty">
        <input
          className="fld num"
          // biome-ignore lint/a11y/noAutofocus: поле открыто нажатием на «Нет данных» — сразу вводить
          autoFocus
          inputMode="decimal"
          aria-label={f.label ?? f.property}
          placeholder="___"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") onDone();
          }}
        />
        {unit && <span className="muted">{unitLabel(unit, i18n.language)}</span>}
        <Button size="sm" className="pillbtn" onPress={save}>
          {t("edit.save")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onPress={() => {
            fill.unknown(f);
            onDone();
          }}
        >
          {t("card.dont_know")}
        </Button>
      </span>
      {f.hint && <span className="muted">{t("card.where", { hint: f.hint })}</span>}
    </div>
  );
}

type Candidate = { value?: ValueLike; atom?: string; quote?: string; source?: string };
type Src = { label?: string };

function Sub({ f }: { f: CardField }) {
  const { t } = useTranslation();
  const src = (f.sources as Src[] | undefined)?.[0]?.label;
  if (f.inherited_from) return <>{t("card.inherited", { from: f.inherited_from })}</>;
  if (f.state === "conflict") return <>{t("card.waits")}</>;
  if (f.state === "asked" && f.ask) return <>{t("card.you_asked", { ask: f.ask })}</>;
  if (f.state === "missing" && f.hint) return <>{t("card.where", { hint: f.hint })}</>;
  return src ? src : null;
}

function Value({ f, open, toggle, fill }: { f: CardField; open: boolean; toggle: () => void; fill?: Fill }) {
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
          {f.default && fill && (
            <Button size="sm" variant="ghost" onPress={() => fill.accept(f)}>
              {t("card.accept")}
            </Button>
          )}
          {fill ? (
            <Button
              size="sm"
              variant="ghost"
              className={f.required ? "need" : "muted"}
              aria-expanded={open}
              onPress={toggle}
            >
              {f.required ? t("card.need") : t("card.missing")}
            </Button>
          ) : f.required ? (
            <span className="need">{t("card.need")}</span>
          ) : (
            !f.default && <span className="muted">{t("card.missing")}</span>
          )}
        </span>
      );
  }
}

/**
 * Имя величины на языке интерфейса. Служба отдаёт подпись поля карточки по-русски; в английском интерфейсе
 * берётся английская подпись словаря property, если она есть, иначе — подпись службы, затем код.
 */
export function usePropertyName() {
  const { i18n } = useTranslation();
  const props = useQuery(q.vocab("property"));
  const en = i18n.language.startsWith("en");
  return (code: string, fallback?: string | null) => {
    const v = props.data?.find((p) => p.code === code);
    return (en ? v?.label.en : undefined) ?? fallback ?? v?.label.ru ?? code.replaceAll("_", " ");
  };
}

function Row({ f, fill }: { f: CardField; fill?: Fill }) {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const name = usePropertyName()(f.property, f.label);
  const atom = f.atoms?.[0];
  return (
    <li className="crow" data-state={f.state}>
      <span className="crow__name">
        {atom ? <Link {...recordPath(atom)}>{name}</Link> : name}
        <span className="crow__sub">
          <Sub f={f} />
        </span>
      </span>
      <Value f={f} open={open} toggle={() => setOpen((o) => !o)} fill={fill} />
      {f.state === "missing" && open && fill && <FillForm f={f} fill={fill} onDone={() => setOpen(false)} />}
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
export function CardTable({
  groups,
  fill,
}: {
  groups: { name: string | null; fields: CardField[] }[];
  fill?: Fill;
}) {
  const { t } = useTranslation();
  return (
    <div className="ctable">
      {groups.map((g) => (
        <section key={g.name ?? "-"} aria-label={g.name ?? t("card.other")}>
          <h2>{g.name ?? t("card.other")}</h2>
          <ul>
            {g.fields.map((f) => (
              <Row key={f.property} f={f} fill={fill} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

type Extra = { property: string; atom: string; value?: ValueLike | null; status?: string };

/** Значения из записей о сущности, которых нет в профиле (или профиля нет вовсе): свойство, значение, статус. */
export function ExtraValues({ items }: { items: unknown[] }) {
  const { t, i18n } = useTranslation();
  const name = usePropertyName();
  const rows = items as Extra[];
  if (!rows.length) return null;
  return (
    <div className="ctable">
      <section aria-label={t("card.extra")}>
        <h2>{t("card.extra")}</h2>
        <ul>
          {rows.map((x) => (
            <li className="crow" key={`${x.atom}-${x.property}`}>
              <span className="crow__name">
                <Link {...recordPath(x.atom)}>{name(x.property)}</Link>
                <span className="crow__sub">{x.status ? t(`status.${x.status}`) : ""}</span>
              </span>
              <span className="cval">
                <span className="num">{formatValue(x.value, i18n.language)}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
