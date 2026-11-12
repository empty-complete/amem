// Правая панель записи: «Источник» и «Окрестность» (граф) вкладками. Ширину меняют разделителем (мышь, касание,
// стрелки), панель сворачивается в узкую полосу; ширина, вкладка и свёрнутость запоминаются на этом устройстве.
import { Button, Tabs } from "@heroui/react";
import { type KeyboardEvent, type PointerEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { useCorePlugin } from "../settings/store";
import { Sky } from "../sky/Sky";
import { SourcePanel } from "../source/SourcePanel";

type Source = components["schemas"]["RecordView"]["sources"][number];

const KEY = "amemo.side";
export const SIDE_MIN = 300;
export const SIDE_MAX = 900;
const SIDE_DEFAULT = 440;

type Saved = { width: number; tab: "source" | "sky"; collapsed: boolean };

function load(): Saved {
  const base: Saved = { width: SIDE_DEFAULT, tab: "source", collapsed: false };
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Partial<Saved>;
    return {
      width: typeof v.width === "number" ? Math.min(SIDE_MAX, Math.max(SIDE_MIN, v.width)) : base.width,
      tab: v.tab === "sky" ? "sky" : "source",
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
  const { t } = useTranslation();
  const [saved, setS] = useState(load);
  // «Окрестность» — плагин ядра: выключен в настройках — вкладки нет, панель показывает источник
  const sky = useCorePlugin("sky.record");
  const s = sky ? saved : { ...saved, tab: "source" as const };
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
      <Tabs
        className="side__tabs"
        selectedKey={s.tab}
        onSelectionChange={(k) => update({ tab: k === "sky" ? "sky" : "source" })}
      >
        <div className="side__bar">
          <Tabs.ListContainer>
            <Tabs.List aria-label={t("side.title")}>
              <Tabs.Tab id="source">
                {t("source.panel")}
                <Tabs.Indicator />
              </Tabs.Tab>
              {sky && (
                <Tabs.Tab id="sky">
                  {t("sky.widget")}
                  <Tabs.Indicator />
                </Tabs.Tab>
              )}
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
        <Tabs.Panel id="source" className="side__panel">
          <SourcePanel sources={sources} basis={basis} active={active} onActive={onActive} />
        </Tabs.Panel>
        {sky && (
          <Tabs.Panel id="sky" className="side__panel side__panel--sky">
            <Sky centerRef={recordRef} height="100%" />
          </Tabs.Panel>
        )}
      </Tabs>
    </div>
  );
}
