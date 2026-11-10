// кнопки своего заголовка окна (decorations: false); window.__TAURI__ — withGlobalTauri в tauri.conf.json
const current = window.__TAURI__?.window.getCurrentWindow();
document.querySelectorAll(".titlebar-buttons button").forEach((button) => {
  button.addEventListener("click", () => {
    if (!current) return;
    const action = button.dataset.action;
    if (action === "minimize") current.minimize();
    else if (action === "maximize") current.toggleMaximize();
    else if (action === "close") current.close();       // приложение прячет окно, а не завершается
  });
});
