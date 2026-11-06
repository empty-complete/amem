import type { ComponentType } from "react";

export type Lang = "ru" | "en";
export type Text = Record<Lang, string>;
/** Места в раскладке экрана, куда оболочка ставит виджеты. */
export type Slot = "main" | "side" | "rail" | "bottom";

export interface WidgetProps {
  recordRef?: string;
  params?: Record<string, string>;
}

/** Виджет: часть экрана с объявленным контрактом (разд. 7.2 спецификации). */
export interface Widget {
  id: string;
  title: Text;
  slots: Slot[];
  component: ComponentType<WidgetProps>;
}

export interface CommandContext {
  navigate: (to: string) => void;
}

/** Команда палитры и клавиш. */
export interface Command {
  id: string;
  title: Text;
  keys?: string;
  run: (ctx: CommandContext) => void | Promise<void>;
}

/** Источник данных: адаптер к контракту службы (amem, позже asearch). */
export interface DataSource {
  id: string;
  kind: "records" | "files" | "graph";
  search: (q: string) => Promise<{ items: unknown[] }>;
}

/** Плагин регистрирует в оболочке виджеты, команды и источники данных. Ядро amem — первый плагин. */
export interface Plugin {
  id: string;
  title?: Text;
  widgets?: Widget[];
  commands?: Command[];
  dataSources?: DataSource[];
}
