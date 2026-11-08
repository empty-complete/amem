import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : "list",
  use: { baseURL: "http://127.0.0.1:5173/ui/", trace: "retain-on-failure", locale: "ru-RU" },
  webServer: [
    {
      command: "npm run dev:mock",
      url: "http://127.0.0.1:5173/ui/",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // сборка с моками под CSP службы — проект «csp»
      command: "npm run build:mock && npx vite preview --outDir dist-mock --port 5174 --strictPort",
      url: "http://127.0.0.1:5174/ui/",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
  projects: [
    {
      name: "desktop",
      testIgnore: /csp\.spec/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    { name: "phone", testIgnore: /csp\.spec/, use: { ...devices["Pixel 7"] } },
    {
      name: "csp",
      testMatch: /csp\.spec/,
      use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:5174/ui/" },
    },
  ],
});
