// Содержание записи сверх значений: формула (content.formula) и таблица (content.table) — схема v1.
// Формула — KaTeX лениво, через тот же санитайзер, что тело; пока грузится — запись plain текстом.
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { unitLabel } from "../../ui/format";
import { type LangString, text } from "./doc";
import { renderMath } from "./markdown";

export type Formula = {
  latex: string;
  plain?: string | null;
  symbols?: { symbol: string; label?: LangString | null; unit?: string | null }[] | null;
};
export type Table = {
  columns: { code: string; label: LangString; unit?: string | null }[];
  rows?: unknown[] | null;
};
export type Content = { formula?: Formula | null; table?: Table | null };

/** LaTeX в элемент: очищенный фрагмент вместо текста-заглушки; ошибка загрузки — заглушка остаётся. */
function TeX({ latex, fallback, display }: { latex: string; fallback: string; display: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let live = true;
    renderMath(latex, display)
      .then((frag) => {
        if (live && ref.current) ref.current.replaceChildren(frag);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [latex, display]);
  return (
    <span ref={ref} className={display ? "formula__math" : "formula__sym"}>
      {fallback}
    </span>
  );
}

function FormulaBlock({ f }: { f: Formula }) {
  const { t, i18n } = useTranslation();
  const symbols = f.symbols ?? [];
  return (
    <section className="widget formula" aria-label={t("content.formula")}>
      <h2>{t("content.formula")}</h2>
      <TeX latex={f.latex} fallback={f.plain || f.latex} display />
      {symbols.length > 0 && (
        <dl className="formula__where" aria-label={t("content.where")}>
          {symbols.map((s) => (
            <div key={s.symbol}>
              <dt>
                <TeX latex={s.symbol} fallback={s.symbol} display={false} />
              </dt>
              <dd>
                {s.label ? text(s.label, i18n.language) : ""}
                {s.unit ? <span className="muted">, {unitLabel(s.unit, i18n.language)}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/** Ячейка: число — по правилам языка и табличными цифрами; пусто — тире; прочее — как есть. */
function cell(v: unknown, lang: string) {
  if (v == null || v === "") return "—";
  if (typeof v === "number") return new Intl.NumberFormat(lang, { maximumFractionDigits: 6 }).format(v);
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Строка таблицы — массив по порядку столбцов или объект по кодам столбцов (схема допускает любое). */
function rowValues(row: unknown, codes: string[]): unknown[] {
  if (Array.isArray(row)) return codes.map((_, i) => row[i]);
  if (row && typeof row === "object") return codes.map((c) => (row as Record<string, unknown>)[c]);
  return [row];
}

function TableBlock({ table }: { table: Table }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const codes = table.columns.map((c) => c.code);
  const rows = table.rows ?? [];
  return (
    <section className="widget" aria-label={t("content.table")}>
      <h2>{t("content.table")}</h2>
      {/* biome-ignore lint/a11y/noNoninteractiveTabindex: широкую таблицу листают клавиатурой (WCAG 2.1.1) */}
      <section className="ctab" tabIndex={0} aria-label={t("content.table_scroll")}>
        <table>
          <thead>
            <tr>
              {table.columns.map((c) => (
                <th key={c.code} scope="col">
                  {text(c.label, lang) || c.code}
                  {c.unit ? <span className="muted">, {unitLabel(c.unit, lang)}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              // строки без своего ключа — порядок и есть их имя
              // biome-ignore lint/suspicious/noArrayIndexKey: строки таблицы не переставляются
              <tr key={i}>
                {rowValues(row, codes).map((v, j) => (
                  <td key={codes[j] ?? j} data-num={typeof v === "number" || undefined}>
                    {cell(v, lang)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {rows.length === 0 && <p className="muted">{t("content.table_empty")}</p>}
    </section>
  );
}

/** Формула и таблица записи; нет ни того ни другого — ничего. */
export function RecordContent({ content }: { content?: Content | null }) {
  if (!content?.formula && !content?.table?.columns?.length) return null;
  return (
    <>
      {content.formula?.latex && <FormulaBlock f={content.formula} />}
      {!!content.table?.columns?.length && <TableBlock table={content.table} />}
    </>
  );
}
