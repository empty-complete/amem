// Папки (контракт v1, часть 4a): создать, переименовать с вложенными и записями, удалить пустую.
// Путь папки — один сегмент адреса: openapi-fetch кодирует его целиком, «/» внутри становится %2F.
import { api, data } from "./client";

export const folderApi = {
  create: async (path: string) => data(await api.POST("/folders", { body: { path } })),
  rename: async (from: string, to: string) =>
    data(await api.PATCH("/folders/{path}", { params: { path: { path: from } }, body: { path: to } })),
  remove: async (path: string) => {
    await api.DELETE("/folders/{path}", { params: { path: { path } } });
  },
};
