import { api, data } from "../api/client";
import type { Plugin } from "./plugin";

/** Ядро amemo — первый плагин оболочки: источник данных записей и команды; виджеты добавляются по частям B–F. */
export const corePlugin: Plugin = {
  id: "amemo",
  title: { ru: "Ядро amemo", en: "amemo core" },
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
      keys: "⌘,",
      run: ({ navigate }) => navigate("/settings"),
    },
  ],
};
