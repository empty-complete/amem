import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// под нагрузкой (полный прогон, CI) ленивые куски и моки отвечают дольше секунды
configure({ asyncUtilTimeout: 3000 });

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

if (typeof window !== "undefined" && typeof globalThis.ResizeObserver === "undefined") {
  // jsdom не знает ResizeObserver; вкладкам HeroUI он нужен только для индикатора
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (typeof Element !== "undefined" && !Element.prototype.getAnimations) {
  // jsdom без Web Animations; React Aria ждёт окончания анимаций при смене вкладок
  Element.prototype.getAnimations = () => [];
}

import { setupI18n } from "../app/i18n";

if (typeof document !== "undefined") await setupI18n("ru");

import { db } from "../mocks/db";
import { writeLog } from "../mocks/handlers-d";
import { server } from "../mocks/node";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  db.reset();
  writeLog.length = 0;
});
afterAll(() => server.close());
