// Правая панель записи: вкладки — виджеты места side из реестра плагинов («Источник», «Окрестность» ядра и вкладки
// других плагинов). Ширину меняют разделителем (мышь, касание, стрелки), панель сворачивается в узкую полосу;
// ширина, вкладка и свёрнутость запоминаются на этом устройстве.
import { Button, Tabs } from "@heroui/react";
import { type KeyboardEvent, type PointerEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { components } from "../../api/schema";
import { registry } from "../../app/registry-instance";
import { Icon } from "../../ui/icons";
import { useCoreOff } from "../settings/store";
import { SideContext } from "./side";

type Source = components["schemas"]["RecordView"]["sources"][number];

const KEY = "amemo.side";
export const SIDE_MIN = 300;
export const SIDE_MAX = 900;
const SIDE_DEFAULT = 440;

type Saved = { width: number; tab: string; collapsed: boolean };

function load(): Saved {
  const base: Saved = { width: SIDE_DEFAULT, tab: "source", collapsed: false };
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Partial<Saved>;
    return {
      width: typeof v.width === "number" ? Math.min(SIDE_MAX, Math.max(SIDE_MIN, v.width)) : base.width,
      // прежнее имя вкладки графа — sky
      tab: v.tab === "sky" ? "sky.record" : typeof v.tab === "string" ? v.tab : "source",
      collapsed: v.collapsed === true,
    };
  } catch {
    return base;
  }
}

function save(v: Saved) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    // нет хранилища (приватное окно) — раскладка просто не запомнится
  }
}

export function SidePanel({
  recordRef,
  sources,
  basis,
  active,
  onActive,
}: {
  recordRef: string;
  sources: Source[];
  basis?: string | null;
  active: number;
  onActive: (i: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language.startsWith("en") ? "en" : "ru";
  const [saved, setS] = useState(load);
  // вкладки — виджеты места side; выключенный в настройках плагин ядра вкладки не даёт
  const off = useCoreOff();
  const tabs = registry.widgetsFor("side").filter((w) => !w.toggle || !off.has(w.toggle));
  const s = tabs.some((w) => w.id === saved.tab) ? saved : { ...saved, tab: tabs[0]?.id ?? "source" };
  const update = (patch: Partial<Saved>) =>
    setS((prev) => {
      const next = { ...prev, ...patch };
      save(next);
      return next;
    });
  const box = useRef<HTMLDivElement>(null);
  const clamp = (w: number) => Math.round(Math.min(SIDE_MAX, Math.max(SIDE_MIN, w)));

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    const right = box.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (ev: globalThis.PointerEvent) =>
      setS((prev) => ({ ...prev, width: clamp(right - ev.clientX) }));
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      setS((prev) => {
        save(prev);
        return prev;
      });
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 96 : 24;
    const to =
      e.key === "ArrowLeft"
        ? s.width + step
        : e.key === "ArrowRight"
          ? s.width - step
          : e.key === "Home"
            ? SIDE_MAX
            : e.key === "End"
              ? SIDE_MIN
              : null;
    if (to == null) return;
    e.preventDefault();
    update({ width: clamp(to) });
  };

  if (s.collapsed) {
    return (
      <div className="side side--collapsed">
        <Button
          isIconOnly
          size="sm"
          variant="ghost"
          aria-label={t("side.expand")}
          aria-expanded={false}
          onPress={() => update({ collapsed: false })}
        >
          <Icon name="chev" style={{ rotate: "180deg" }} />
        </Button>
      </div>
    );
  }
  return (
    <div ref={box} className="side" style={{ width: s.width }}>
      {/* biome-ignore lint/a11y/useSemanticElements: разделитель с изменяемым значением — role=separator, а не <hr> */}
      <div
        className="side__grip"
        role="separator"
        aria-orientation="vertical"
        aria-label={t("side.width")}
        aria-valuemin={SIDE_MIN}
        aria-valuemax={SIDE_MAX}
        aria-valuenow={s.width}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onKeyDown={onKey}
      />
      <SideContext.Provider value={{ sources, basis, active, onActive }}>
        <Tabs
          className="side__tabs"
          selectedKey={s.tab}
          onSelectionChange={(k) => update({ tab: String(k) })}
        >
          <div className="side__bar">
            <Tabs.ListContainer>
              <Tabs.List aria-label={t("side.title")}>
                {tabs.map((w) => (
                  <Tabs.Tab key={w.id} id={w.id}>
                    {w.title[lang]}
                    <Tabs.Indicator />
                  </Tabs.Tab>
                ))}
              </Tabs.List>
            </Tabs.ListContainer>
            <Button
              isIconOnly
              size="sm"
              variant="ghost"
              aria-label={t("side.collapse")}
              aria-expanded
              onPress={() => update({ collapsed: true })}
            >
              <Icon name="chev" />
            </Button>
          </div>
          {tabs.map((w) => (
            <Tabs.Panel
              key={w.id}
              id={w.id}
              className={w.panelClass ? `side__panel ${w.panelClass}` : "side__panel"}
            >
              <w.component recordRef={recordRef} />
            </Tabs.Panel>
          ))}
        </Tabs>
      </SideContext.Provider>
    </div>
  );
}
