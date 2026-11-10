/** Мастер первого запуска приложения amemo для Windows (desktop/): точка входа setup.html, своя сборка в
 * dist-setup с относительными путями — её страницы приложение Tauri отдаёт из своих файлов, а не служба по /ui. */

import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  // свой кэш предсборки: dev-сервер веб-интерфейса (Playwright запускает оба) иначе затирал бы общий node_modules/.vite
  cacheDir: "node_modules/.vite-setup",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
    fs: { allow: [".."] }, // анимации — из docs/assets/readme
  },
  preview: { host: "127.0.0.1", port: 5175, strictPort: true },
  build: {
    outDir: "dist-setup",
    emptyOutDir: true,
    rollupOptions: { input: fileURLToPath(new URL("./setup.html", import.meta.url)) },
  },
});
