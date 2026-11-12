// Виджеты правой панели записи (место side): «Источник» и «Окрестность». Данные записи — из контекста панели,
// чтобы виджет плагина получал то же, что и виджеты ядра.
import { createContext, useContext } from "react";
import type { components } from "../../api/schema";
import type { WidgetProps } from "../../app/plugin";
import { Sky } from "../sky/Sky";
import { SourcePanel } from "../source/SourcePanel";

type Source = components["schemas"]["RecordView"]["sources"][number];

export type SideData = {
  sources: Source[];
  basis?: string | null;
  active: number;
  onActive: (i: number) => void;
};

export const SideContext = createContext<SideData | null>(null);

/** Источники записи: файл, место, цитата и сама страница. */
export function SourceWidget() {
  const c = useContext(SideContext);
  if (!c) return null;
  return <SourcePanel sources={c.sources} basis={c.basis} active={c.active} onActive={c.onActive} />;
}

/** Окрестность записи на небе — плагин ядра, выключается в настройках. */
export function NeighbourhoodWidget({ recordRef }: WidgetProps) {
  return recordRef ? <Sky centerRef={recordRef} height="100%" /> : null;
}
