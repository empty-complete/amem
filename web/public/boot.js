// До модулей приложения. Отдельным файлом, потому что служба отдаёт /ui с CSP script-src 'self'
// и встроенный <script> браузер не выполнит. Имя без хэша — служба отдаёт его с no-cache.
(() => {
  // zod 4 без JIT: иначе при первом разборе он проверяет, разрешён ли Function, и сама проверка
  // нарушает CSP. Настройку zod читает из этого объекта; модули ещё не загружены, поэтому — здесь.
  globalThis.__zod_globalConfig = Object.assign(globalThis.__zod_globalConfig || {}, { jitless: true });

  // тема до первой отрисовки, без мигания
  let theme = null;
  try {
    theme = localStorage.getItem("amem.theme");
  } catch {}
  try {
    if (theme !== "light" && theme !== "dark")
      theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.add(theme);
  } catch {}
})();
