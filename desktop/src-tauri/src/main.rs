//! amemo для Windows (спецификация docs/superpowers/specs/2026-11-10-amemo-desktop-installer-design.md, часть D3):
//! одно приложение — окно amemo без системной рамки, значок в области уведомлений, единственный экземпляр, проверка
//! обновлений. Мастер первого запуска (D4), запуск базы и службы (D5), плагин Claude (D6) и установка обновлений (D7)
//! добавляются следующими частями.
//!
//! - Закрытие окна его прячет, а не завершает приложение: базой и службой пользуются агенты и без окна. Выход — пункт
//!   «Выход» значка.
//! - Второй запуск (значок на рабочем столе, меню «Пуск») не создаёт второй процесс, а выводит окно вперёд.
//! - `--background` — запуск без окна (автозапуск при входе в Windows, D5).
//! - Размер и положение окна запоминаются; видимость — нет: окно показывает приложение.
//! - Обновление проверяется при запуске (`latest.json` последнего релиза, подпись — ключом из tauri.conf.json); пока
//!   только сообщается в журнал, установка — D7.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, WindowEvent,
};
use tauri_plugin_updater::UpdaterExt;
use tauri_plugin_window_state::StateFlags;

const MAIN: &str = "main";
const BACKGROUND: &str = "--background";

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItemBuilder::with_id("open", "Открыть amemo").build(app)?;
    // «Пауза» остановит службу и базу, когда приложение начнёт ими управлять (D5)
    let pause = MenuItemBuilder::with_id("pause", "Пауза").enabled(false).build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Выход").build(app)?;
    let menu = MenuBuilder::new(app)
        .items(&[&open, &pause])
        .separator()
        .items(&[&quit])
        .build()?;
    let mut builder = TrayIconBuilder::with_id("amemo")
        .tooltip("amemo")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

async fn check_update(app: AppHandle) {
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(e) => {
            eprintln!("amemo: обновления недоступны: {e}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => eprintln!("amemo: доступна версия {} (установка — следующей частью)", update.version),
        Ok(None) => {}
        Err(e) => eprintln!("amemo: проверка обновлений не удалась: {e}"),
    }
}

fn main() {
    let background = std::env::args().any(|arg| arg == BACKGROUND);
    tauri::Builder::default()
        // первым: второй экземпляр завершается до того, как что-то создаст
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::all() & !StateFlags::VISIBLE)
                .build(),
        )
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(move |app| {
            tray(app.handle())?;
            if !background {
                show_main(app.handle());
            }
            tauri::async_runtime::spawn(check_update(app.handle().clone()));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("amemo: приложение не запустилось");
}
