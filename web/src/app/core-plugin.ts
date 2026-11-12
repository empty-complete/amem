import { api, data } from "../api/client";
import { NeighbourhoodWidget, SourceWidget } from "../features/record/side";
import { settingsWindow } from "../features/settings/store";
import { MOD } from "../ui/platform";
import type { Plugin } from "./plugin";

/** Ядро amemo — первый плагин оболочки: источник данных записей, команды и виджеты правой панели записи. */
export const corePlugin: Plugin = {
  id: "amemo",
  title: { ru: "Ядро amemo", en: "amemo core" },
  widgets: [
    { id: "source", title: { ru: "Источник", en: "Source" }, slots: ["side"], component: SourceWidget },
    {
      id: "sky.record",
      title: { ru: "Окрестность", en: "Neighbourhood" },
      slots: ["side"],
      component: NeighbourhoodWidget,
      toggle: "sky.record",
      panelClass: "side__panel--sky",
    },
  ],
  dataSources: [
    {
      id: "amemo.records",
      kind: "records",
      search: async (qs) => {
        const r = data(await api.GET("/search", { params: { query: { q: qs, limit: 10 } } }));
        return { items: r.items };
      },
    },
  ],
  commands: [
    {
      id: "amemo.records",
      title: { ru: "Все записи", en: "All records" },
      run: ({ navigate }) => navigate("/records"),
    },
    {
      id: "amemo.new",
      title: { ru: "Записать", en: "Write" },
      keys: "N",
      run: ({ navigate }) => navigate("/new"),
    },
    {
      id: "amemo.review",
      title: { ru: "Открыть проверку", en: "Open review" },
      keys: "G R",
      run: ({ navigate }) => navigate("/review"),
    },
    {
      id: "amemo.changes",
      title: { ru: "Открыть изменения", en: "Open changes" },
      keys: "G C",
      run: ({ navigate }) => navigate("/changes"),
    },
    {
      id: "amemo.settings",
      title: { ru: "Настройки", en: "Settings" },
      keys: `${MOD},`,
      run: () => settingsWindow.open(),
    },
  ],
};
