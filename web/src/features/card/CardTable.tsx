import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { formatValue, unitLabel, type ValueLike } from "../../ui/format";
import { Icon } from "../../ui/icons";
import { humanize, useVocabLabel } from "../../ui/useVocabLabel";
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

/** Подписи словаря величин строчные («рабочая температура») — в названии поля с заглавной, как подписи видов. */
const cap = (s: string) => s.charAt(0).toLocaleUpperCase() + s.slice(1);

type Candidate = { value?: ValueLike; atom?: string; quote?: string; source?: string };
type Src = { label?: string };

/** Подстрока поля по форме ядра: где искать (hint) и у кого спросить (ask) — когда значения нет; когда поле нужно
 * (when); откуда обычно берётся значение (origin, словарь parameter_origin); у asked — ссылка на заданный вопрос. */
function Sub({ f }: { f: CardField }) {
  const { t } = useTranslation();
  const origin = useVocabLabel("parameter_origin");
  const parts: ReactNode[] = [];
  const src = (f.sources as Src[] | undefined)?.[0]?.label;
  if (f.inherited_from) parts.push(t("card.inherited", { from: f.inherited_from }));
  if (f.state === "conflict") parts.push(t("card.waits"));
  if (f.state === "asked") {
    // вопрос — атом из atoms (ядро дописывает вопросы в конец); старая форма — текст ask
    const question = f.atoms?.at(-1);
    parts.push(
      question ? (
        <Link key="q" {...recordPath(question)}>
          {t("card.question_open")}
        </Link>
      ) : (
        t("card.you_asked", { ask: f.ask ?? "" })
      ),
    );
  }
  if (f.state === "missing") {
    if (f.hint) parts.push(t("card.where", { hint: f.hint }));
    if (f.ask) parts.push(t("card.ask_whom", { who: f.ask }));
  }
  if (f.state === "known" && src) parts.push(src);
  if (f.when && f.state !== "known") parts.push(t("card.when", { when: f.when }));
  if (f.origin) parts.push(origin(f.origin) ?? humanize(f.origin));
  if (!parts.length) return null;
  return (
    <>
      {parts.map((p, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: части строки не переставляются
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
    </>
  );
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
      <span className="crow__name" title={f.rule ? t("card.rule", { rule: f.rule }) : undefined}>
        {atom && f.state !== "asked" ? <Link {...recordPath(atom)}>{cap(name)}</Link> : cap(name)}
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
  // группа правила — код; подпись — из необязательного словаря пакета parameter_group
  const groupLabel = useVocabLabel("parameter_group");
  const title = (name: string | null) =>
    name ? (groupLabel(name) ?? (/^[a-z][a-z0-9_]*$/.test(name) ? humanize(name) : name)) : t("card.other");
  return (
    <div className="ctable">
      {groups.map((g) => (
        <section key={g.name ?? "-"} aria-label={title(g.name)}>
          <h2>{title(g.name)}</h2>
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
