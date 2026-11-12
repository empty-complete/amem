import type { ComponentType } from "react";

export type Lang = "ru" | "en";
export type Text = Record<Lang, string>;
/** Места в раскладке экрана, куда оболочка ставит виджеты. */
export type Slot = "main" | "side" | "rail" | "bottom";

export interface WidgetProps {
  recordRef?: string;
  params?: Record<string, string>;
}

/** Виджет: часть экрана с объявленным контрактом (разд. 7.2 спецификации). Место side — вкладка правой панели
 * записи: плагин добавляет свою вкладку, не трогая оболочку. */
export interface Widget {
  id: string;
  title: Text;
  slots: Slot[];
  component: ComponentType<WidgetProps>;
  /** Переключатель «Плагины ядра» в настройках: выключен — виджета нет; без него виджет всегда на месте. */
  toggle?: string;
  /** Класс панели виджета в своём месте (например, граф — на всю высоту без отступов). */
  panelClass?: string;
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

/** Источник данных: адаптер к контракту службы (amemo, позже asearch). */
export interface DataSource {
  id: string;
  kind: "records" | "files" | "graph";
  search: (q: string) => Promise<{ items: unknown[] }>;
}

/** Плагин регистрирует в оболочке виджеты, команды и источники данных. Ядро amemo — первый плагин. */
export interface Plugin {
  id: string;
  title?: Text;
  widgets?: Widget[];
  commands?: Command[];
  dataSources?: DataSource[];
}
