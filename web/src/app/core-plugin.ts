import { api, data } from "../api/client";
import type { Plugin } from "./plugin";

/** Ядро amem — первый плагин оболочки: источник данных записей и команды; виджеты добавляются по частям B–F. */
export const corePlugin: Plugin = {
  id: "amem",
  title: { ru: "Ядро amem", en: "amem core" },
  dataSources: [
    {
      id: "amem.records",
      kind: "records",
      search: async (qs) => {
        const r = data(await api.GET("/search", { params: { query: { q: qs, limit: 10 } } }));
        return { items: r.items };
      },
    },
  ],
  commands: [
    {
      id: "amem.new",
      title: { ru: "Записать", en: "Write" },
      keys: "N",
      run: ({ navigate }) => navigate("/new"),
    },
    {
      id: "amem.review",
      title: { ru: "Открыть проверку", en: "Open review" },
      keys: "G R",
      run: ({ navigate }) => navigate("/review"),
    },
    {
      id: "amem.settings",
      title: { ru: "Настройки", en: "Settings" },
      keys: "⌘,",
      run: ({ navigate }) => navigate("/settings"),
    },
  ],
};
