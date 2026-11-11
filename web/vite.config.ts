/// <reference types="vitest/config" />

import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig } from "vite";

/** CSP, с которой служба отдаёт /ui (amemo/service/ui.py). Та же — у `vite preview`, чтобы нарушения ловились
 * до службы. В `vite dev` её нет: горячая замена модулей вставляет встроенные скрипты. */
export const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; " +
  "form-action 'self'";

export default defineConfig({
  base: "/ui/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    msw({ mode: "worker-only" }),
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // служба amemo serve по умолчанию — 127.0.0.1:8767; другой адрес — AMEMO_URL
    proxy: { "/api": { target: process.env.AMEMO_URL ?? "http://127.0.0.1:8767", changeOrigin: true } },
  },
  preview: {
    host: "127.0.0.1",
    headers: { "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff" },
    proxy: { "/api": { target: process.env.AMEMO_URL ?? "http://127.0.0.1:8767", changeOrigin: true } },
  },
  build: {
    outDir: "python/amemo_web/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        // CodeMirror делят исходник и редактор тела — один ленивый кусок с понятным именем для бюджета;
        // docx-preview с jszip — свой ленивый кусок: грузится, только когда открыт источник DOCX
        manualChunks: (id) =>
          /node_modules\/(@codemirror|@lezer|crelt|style-mod|w3c-keyname)\//.test(id)
            ? "codemirror"
            : /node_modules\/(docx-preview|jszip|pako|lie|immediate|setimmediate)\//.test(id)
              ? "docx"
              : undefined,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.ts"],
    css: false,
  },
});
