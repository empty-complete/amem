import { Tabs } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";

export type CitedRange = { sheet: string; range: string; label: string };

const col = (letters: string) =>
  [...letters.toUpperCase()].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
const letter = (n: number): string =>
  n <= 0 ? "" : letter(Math.floor((n - 1) / 26)) + String.fromCharCode(65 + ((n - 1) % 26));

/** «B4:C9» → границы в номерах (1 — первая строка, A — первый столбец). */
export function parseRange(r: string) {
  const m = r.match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/i);
  if (!m) return null;
  const c1 = col(m[1] as string);
  const r1 = Number(m[2]);
  const c2 = m[3] ? col(m[3]) : c1;
  const r2 = m[4] ? Number(m[4]) : r1;
  return { c1: Math.min(c1, c2), c2: Math.max(c1, c2), r1: Math.min(r1, r2), r2: Math.max(r1, r2) };
}

function Sheet({
  id,
  version,
  name,
  cited,
  onPick,
}: {
  id: string;
  version: number;
  name: string;
  cited: CitedRange[];
  onPick?: (sheet: string, range: string) => void;
}) {
  const [drag, setDrag] = useState<{ r1: number; c1: number; r2: number; c2: number } | null>(null);
  const [down, setDown] = useState(false);
  const picked = (r: number, c: number) =>
    !!drag &&
    r >= Math.min(drag.r1, drag.r2) &&
    r <= Math.max(drag.r1, drag.r2) &&
    c >= Math.min(drag.c1, drag.c2) &&
    c <= Math.max(drag.c1, drag.c2);
  const finish = (d: typeof drag) => {
    setDown(false);
    if (!d || !onPick) return;
    const a = `${letter(Math.min(d.c1, d.c2))}${Math.min(d.r1, d.r2)}`;
    const b = `${letter(Math.max(d.c1, d.c2))}${Math.max(d.r1, d.r2)}`;
    onPick(name, a === b ? a : `${a}:${b}`);
  };
  const { t } = useTranslation();
  const s = useQuery(q.sheet(id, version, name));
  if (s.isPending) return <RegionState state="loading" />;
  if (s.isError) return <RegionState state="error" message={errorText(s.error, t("region.offline"))} />;
  const start = parseRange(s.data.range.split(":")[0] ?? "A1") ?? { r1: 1, c1: 1 };
  const ranges = cited.filter((c) => c.sheet === name).map((c) => ({ ...c, box: parseRange(c.range) }));
  const hit = (r: number, c: number) =>
    ranges.some(({ box }) => box && r >= box.r1 && r <= box.r2 && c >= box.c1 && c <= box.c2);
  const width = Math.max(...s.data.rows.map((r) => r.length), 1);
  return (
    <div className="sheet">
      <section
        className="sheet__scroll"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: прокручиваемая таблица должна получать фокус с клавиатуры
        tabIndex={0}
        aria-label={t("source.sheet_label", { name })}
      >
        <table aria-label={t("source.sheet_label", { name })}>
          <thead>
            <tr>
              <td />
              {Array.from({ length: width }, (_, i) => (
                <th key={letter(start.c1 + i)} scope="col">
                  {letter(start.c1 + i)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {s.data.rows.map((row, ri) => {
              const r = start.r1 + ri;
              return (
                <tr key={r}>
                  <th scope="row">{r}</th>
                  {Array.from({ length: width }, (_, ci) => {
                    const c = start.c1 + ci;
                    const v = row[ci];
                    const on = hit(r, c);
                    return (
                      <td
                        key={c}
                        data-cited={on || undefined}
                        data-picked={picked(r, c) || undefined}
                        onPointerDown={
                          onPick
                            ? (e) => {
                                e.preventDefault();
                                setDown(true);
                                setDrag({ r1: r, c1: c, r2: r, c2: c });
                              }
                            : undefined
                        }
                        onPointerEnter={
                          onPick && down ? () => setDrag((d) => (d ? { ...d, r2: r, c2: c } : d)) : undefined
                        }
                        onPointerUp={
                          onPick ? () => finish(drag ? { ...drag, r2: r, c2: c } : null) : undefined
                        }
                        className={typeof v === "number" ? "num" : undefined}
                      >
                        {v == null
                          ? ""
                          : typeof v === "number"
                            ? v.toLocaleString("ru").replace("-", "−")
                            : v}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {ranges.map((c) => (
        <p key={`${c.range}-${c.label}`} className="sheet__cap">
          <i aria-hidden="true" /> {t("source.cited_cell", { range: c.range, label: c.label })}
        </p>
      ))}
    </div>
  );
}

/** Превью таблицы: вкладки листов, ячейки, на которые ссылаются записи, подсвечены. */
export function SheetPreview({
  id,
  version,
  sheets,
  cited,
  onPick,
}: {
  id: string;
  version: number;
  sheets: string[];
  cited: CitedRange[];
  /** Протяжка по ячейкам — диапазон для «+ Источник». */
  onPick?: (sheet: string, range: string) => void;
}) {
  const first = cited[0]?.sheet && sheets.includes(cited[0].sheet) ? cited[0].sheet : (sheets[0] ?? "");
  const [sel, setSel] = useState(first);
  const { t } = useTranslation();
  return (
    <Tabs selectedKey={sel} onSelectionChange={(k) => setSel(String(k))}>
      <Tabs.ListContainer>
        <Tabs.List aria-label={t("source.sheets")}>
          {sheets.map((s) => (
            <Tabs.Tab key={s} id={s}>
              {s}
              <Tabs.Indicator />
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs.ListContainer>
      {sheets.map((s) => (
        <Tabs.Panel key={s} id={s}>
          {s === sel && <Sheet id={id} version={version} name={s} cited={cited} onPick={onPick} />}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
}
