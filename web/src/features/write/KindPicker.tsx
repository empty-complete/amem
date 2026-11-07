import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button, Dialog, DialogTrigger, Popover } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import type { Template } from "./proposal";

const PACK_ORDER = (p: string) => (p === "core" ? 0 : p === "mine" ? 2 : 1);

/** Вид записи плашкой; нажатие — список по пакетам с поиском и «настроить» (не ряд из всех видов: антипример v7). */
export function KindPicker({
  target,
  value,
  onChange,
  onConfigure,
}: {
  target: "atom" | "entity";
  value: string;
  onChange: (t: Template) => void;
  onConfigure?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const en = i18n.language.startsWith("en");
  const list = useQuery(q.templates(target));
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const cur = list.data?.find((x) => x.code === value);
  const groups = useMemo(() => {
    const s = text.trim().toLowerCase();
    const items = (list.data ?? []).filter(
      (x) => !s || x.label.ru?.toLowerCase().includes(s) || x.code.includes(s),
    );
    const by = new Map<string, Template[]>();
    for (const x of items) by.set(x.pack, [...(by.get(x.pack) ?? []), x]);
    return [...by.entries()].sort((a, b) => PACK_ORDER(a[0]) - PACK_ORDER(b[0]));
  }, [list.data, text]);
  const packName = (p: string) =>
    p === "core" ? t("edit.pack_core") : p === "mine" ? t("edit.pack_mine") : p;
  return (
    <DialogTrigger isOpen={open} onOpenChange={setOpen}>
      <Button
        className="pill kind kindbtn"
        data-family={cur?.family ?? "work"}
        aria-label={t("edit.kind_change", { kind: cur?.label.ru ?? value })}
      >
        {(en ? cur?.label.en : cur?.label.ru) ?? value}
        <Icon name="down" size={12} />
      </Button>
      <Popover className="palette kindpop" placement="bottom start">
        <Dialog aria-label={t("record.p_kind")} className="kindpop__in">
          <input
            className="fld"
            // biome-ignore lint/a11y/noAutofocus: список видов открыт по нажатию — сразу искать
            autoFocus
            placeholder={t("edit.kind_search")}
            aria-label={t("edit.kind_search")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {groups.map(([pack, items]) => (
            <div key={pack} role="group" aria-label={packName(pack)}>
              <h4 className="palette__head">{packName(pack)}</h4>
              {items.map((x) => (
                <button
                  key={x.code}
                  type="button"
                  className="palette__opt kindopt"
                  data-family={x.family}
                  aria-pressed={x.code === value}
                  onClick={() => {
                    onChange(x);
                    setOpen(false);
                  }}
                >
                  <i aria-hidden="true" />
                  <span className="palette__label">{(en ? x.label.en : x.label.ru) ?? x.code}</span>
                  {x.description?.ru && <span className="palette__meta">{x.description.ru}</span>}
                </button>
              ))}
            </div>
          ))}
          {onConfigure && (
            <button
              type="button"
              className="navlink"
              onClick={() => {
                setOpen(false);
                onConfigure();
              }}
            >
              <Icon name="pencil" />
              {t("edit.kind_configure")}
            </button>
          )}
        </Dialog>
      </Popover>
    </DialogTrigger>
  );
}
