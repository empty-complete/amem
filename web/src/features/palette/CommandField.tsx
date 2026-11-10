import { useNavigate } from "@tanstack/react-router";
import { forwardRef, type KeyboardEvent, useEffect, useMemo, useState } from "react";
import {
  ComboBox,
  Header,
  Input,
  type Key,
  ListBox,
  ListBoxItem,
  ListBoxSection,
  Popover,
} from "react-aria-components";
import { useTranslation } from "react-i18next";
import type { components } from "../../api/schema";
import type { Command } from "../../app/plugin";
import { registry } from "../../app/registry-instance";
import { Icon } from "../../ui/icons";
import { KindChip } from "../../ui/KindChip";
import { MOD_KEY } from "../../ui/platform";
import { recordPath } from "../records/RecordList";
import "./palette.css";

type Hit = components["schemas"]["SearchHit"];
type Item = { id: string; kind: "record"; hit: Hit } | { id: string; kind: "command"; cmd: Command };

function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const id = setTimeout(() => setD(v), ms);
    return () => clearTimeout(id);
  }, [v, ms]);
  return d;
}

/** Поле поиска и командная строка: записи по запросу и команды реестра; Enter без выбора — все результаты. */
export const CommandField = forwardRef<HTMLInputElement>(function CommandField(_, ref) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const lang = i18n.language.startsWith("en") ? "en" : "ru";
  const [text, setText] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const query = useDebounced(text.trim(), 150);

  useEffect(() => {
    if (!query) {
      setHits([]);
      return;
    }
    let live = true;
    const src = registry.dataSources.get("amemo.records");
    src
      ?.search(query)
      .then((r) => live && setHits((r.items as Hit[]).slice(0, 6)))
      .catch(() => live && setHits([]));
    return () => {
      live = false;
    };
  }, [query]);

  const commands = useMemo(() => {
    const s = text.trim().toLowerCase();
    if (!s) return [];
    return [...registry.commands.values()].filter((c) => c.title[lang].toLowerCase().includes(s));
  }, [text, lang]);

  const sections: { name: string; items: Item[] }[] = [
    {
      name: t("palette.records"),
      items: hits.map((hit) => ({ id: `r:${hit.ref}`, kind: "record" as const, hit })),
    },
    {
      name: t("palette.commands"),
      items: commands.map((cmd) => ({ id: `c:${cmd.id}`, kind: "command" as const, cmd })),
    },
  ].filter((s) => s.items.length);

  const all = sections.flatMap((s) => s.items);
  const pick = (key: Key | null) => {
    const it = all.find((i) => i.id === key);
    if (!it) return;
    setText("");
    if (it.kind === "record") navigate(recordPath(it.hit.ref));
    else it.cmd.run({ navigate: (to) => navigate({ to: to as never }) });
  };
  const toResults = () => {
    const v = text.trim();
    if (v) navigate({ to: "/search", search: { q: v, kind: [], status: [], limit: 10 } });
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // Enter без подсвеченного варианта — к странице результатов
    if (e.key === "Enter" && !e.currentTarget.getAttribute("aria-activedescendant")) toResults();
  };

  return (
    <ComboBox
      className="bar__search"
      aria-label={t("nav.search")}
      inputValue={text}
      onInputChange={setText}
      onSelectionChange={pick}
      selectedKey={null}
      allowsCustomValue
      allowsEmptyCollection={false}
      menuTrigger="input"
      items={sections}
    >
      <Icon name="search" />
      <Input ref={ref} type="search" placeholder={t("nav.search")} onKeyDown={onKeyDown} />
      <kbd>{MOD_KEY}</kbd>
      <kbd>K</kbd>
      <Popover className="palette" placement="bottom start" offset={6}>
        <ListBox<{ name: string; items: Item[] }> className="palette__list">
          {(section) => (
            <ListBoxSection id={section.name}>
              <Header className="palette__head">{section.name}</Header>
              {section.items.map((it) =>
                it.kind === "record" ? (
                  <ListBoxItem
                    key={it.id}
                    id={it.id}
                    textValue={it.hit.label ?? it.hit.snippet}
                    className="palette__opt"
                  >
                    {it.hit.kind && <KindChip kind={it.hit.kind} />}
                    <span className="palette__label">{it.hit.label ?? it.hit.snippet}</span>
                    <span className="palette__meta">{it.hit.about?.[0]?.label}</span>
                  </ListBoxItem>
                ) : (
                  <ListBoxItem key={it.id} id={it.id} textValue={it.cmd.title[lang]} className="palette__opt">
                    <Icon name="chev" />
                    <span className="palette__label">{it.cmd.title[lang]}</span>
                    {it.cmd.keys && <kbd>{it.cmd.keys}</kbd>}
                  </ListBoxItem>
                ),
              )}
            </ListBoxSection>
          )}
        </ListBox>
      </Popover>
    </ComboBox>
  );
});
