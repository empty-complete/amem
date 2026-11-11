//! amemo для Windows (спецификация docs/superpowers/specs/2026-11-10-amemo-desktop-installer-design.md): одно
//! приложение — мастер первого запуска, окно amemo без системной рамки, значок в области уведомлений и фон (база и
//! служба для агентов).
//!
//! - Первый запуск — мастер (`web/src/setup`, команды — `setup.rs`). Дальше — экран запуска той же страницы, пока
//!   поднимаются PostgreSQL и служба (`service.rs`), затем окно переходит на веб-интерфейс службы.
//! - Закрытие окна его прячет, а не завершает приложение: базой и службой пользуются агенты и без окна. Значок:
//!   «Открыть amemo», «Пауза» (остановить службу и базу) / «Продолжить», «Выход». Пока мастер не пройден, закрытие
//!   окна завершает приложение.
//! - Второй запуск (значок на рабочем столе, меню «Пуск») не создаёт второй процесс, а выводит окно вперёд.
//! - `--background` — запуск без окна (автозапуск при входе в Windows, его включает мастер).
//! - `--quit` — остановить работающее приложение (службу и базу) и дождаться этого; так его останавливает удаление.
//! - `--setup-unattended CHOICES.json` — установка без окна, по выбору мастера в файле (проверки CI); ход — строки
//!   JSON в stdout, код выхода 0 — готово.
//! - Размер и положение окна запоминаются; видимость — нет: окно показывает приложение.
//! - Обновление проверяется при запуске (`latest.json` последнего релиза); пока только сообщается в журнал,
//!   установка — D7.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod download;
mod log;
mod paths;
mod service;
mod setup;
mod winpath;

use paths::Paths;
use service::{Service, Status};
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{MenuBuilder, MenuItem, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, RunEvent, WindowEvent, Wry,
};
use tauri_plugin_updater::UpdaterExt;
use tauri_plugin_window_state::StateFlags;

const MAIN: &str = "main";
const BACKGROUND: &str = "--background";
const QUIT: &str = "--quit";
const UNATTENDED: &str = "--setup-unattended";

pub struct App {
    pub paths: Paths,
    pub service: Arc<Service>,
    pause: Mutex<Option<MenuItem<Wry>>>,
}

fn configured(app: &AppHandle) -> bool {
    let state = app.state::<App>();
    state.paths.state().setup_done && state.paths.current().is_some()
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn navigate(app: &AppHandle, url: &str) -> Result<(), String> {
    let window = app.get_webview_window(MAIN).ok_or("нет окна amemo")?;
    let url: tauri::Url = url.parse().map_err(|e| format!("{url}: {e}"))?;
    window.navigate(url).map_err(|e| e.to_string())
}

/// Своя страница приложения — экран запуска (тот же setup.html: мастер пройден — он показывает запуск).
fn start_page(app: &AppHandle) {
    let page = if cfg!(windows) { "http://tauri.localhost/setup.html" } else { "tauri://localhost/setup.html" };
    if let Err(e) = navigate(app, page) {
        log!("экран запуска: {e}");
    }
}

/// Дождаться фона и перейти в окно amemo; на паузе без resume — отказ "paused" (экран запуска предлагает
/// «Продолжить»).
pub async fn open_service(app: &AppHandle, resume: bool) -> Result<(), String> {
    let service = app.state::<App>().service.clone();
    match service.status() {
        Status::Paused if !resume => return Err("paused".into()),
        Status::Ready | Status::Starting => {}
        _ => service.start(),
    }
    let mut changes = service.subscribe();
    let status = changes
        .wait_for(|s| matches!(s, Status::Ready | Status::Failed(_) | Status::Paused))
        .await
        .map_err(|e| e.to_string())?
        .clone();
    match status {
        Status::Ready => navigate(app, &Service::url()),
        Status::Failed(message) => Err(message),
        _ => Err("paused".into()),
    }
}

#[tauri::command]
async fn app_start(app: AppHandle) -> Result<(), String> {
    open_service(&app, false).await
}

#[tauri::command]
async fn app_resume(app: AppHandle) -> Result<(), String> {
    open_service(&app, true).await
}

struct Labels {
    open: &'static str,
    pause: &'static str,
    resume: &'static str,
    quit: &'static str,
}

fn labels() -> Labels {
    if setup::ui_lang() == "en" {
        Labels { open: "Open amemo", pause: "Pause", resume: "Resume", quit: "Quit" }
    } else {
        Labels { open: "Открыть amemo", pause: "Пауза", resume: "Продолжить", quit: "Выход" }
    }
}

/// Пункт «Пауза» / «Продолжить» — по состоянию фона; до конца мастера его нет смысла нажимать.
pub fn tray_refresh(app: &AppHandle) {
    let state = app.state::<App>();
    let Ok(pause) = state.pause.lock() else { return };
    let Some(item) = pause.as_ref() else { return };
    let status = state.service.status();
    let text = labels();
    let _ = item.set_text(if status == Status::Paused { text.resume } else { text.pause });
    let _ = item.set_enabled(configured(app) && status != Status::Starting);
}

fn toggle_pause(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        let service = app.state::<App>().service.clone();
        if service.status() == Status::Paused {
            service.start();
        } else {
            service.stop(true);
        }
        start_page(&app);
    });
}

/// Остановить фон и завершиться; ждёт остановки (второй экземпляр с `--quit` ждёт вместе с ним).
fn quit(app: &AppHandle) {
    log!("выход");
    app.state::<App>().service.stop(false);
    app.exit(0);
}

fn tray(app: &AppHandle) -> tauri::Result<()> {
    let text = labels();
    let open = MenuItemBuilder::with_id("open", text.open).build(app)?;
    let pause = MenuItemBuilder::with_id("pause", text.pause).enabled(false).build(app)?;
    let quit_item = MenuItemBuilder::with_id("quit", text.quit).build(app)?;
    let menu = MenuBuilder::new(app).items(&[&open, &pause]).separator().items(&[&quit_item]).build()?;
    if let Ok(mut slot) = app.state::<App>().pause.lock() {
        *slot = Some(pause);
    }
    let mut builder = TrayIconBuilder::with_id("amemo")
        .tooltip("amemo")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => open_window(app),
            "pause" => toggle_pause(app),
            "quit" => quit(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                open_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Открыть окно; фон не готов — сначала экран запуска (он дождётся фона или покажет ошибку и паузу).
fn open_window(app: &AppHandle) {
    if configured(app) && app.state::<App>().service.status() != Status::Ready {
        start_page(app);
    }
    show_main(app);
}

/// Пауза, ошибка и восстановление фона видны в значке; упавший фон уводит окно на экран запуска с ошибкой.
fn follow_status(app: AppHandle) {
    let mut changes = app.state::<App>().service.subscribe();
    tauri::async_runtime::spawn(async move {
        while changes.changed().await.is_ok() {
            let status = changes.borrow_and_update().clone();
            tray_refresh(&app);
            if matches!(status, Status::Failed(_)) {
                start_page(&app);
            }
        }
    });
}

async fn check_update(app: AppHandle) {
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(e) => {
            log!("обновления недоступны: {e}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => log!("доступна версия {} (установка — следующей частью)", update.version),
        Ok(None) => {}
        Err(e) => log!("проверка обновлений не удалась: {e}"),
    }
}

fn unattended(paths: &Paths, version: &str, file: Option<&str>) -> i32 {
    let Some(file) = file else {
        log!("{UNATTENDED}: нужен файл с выбором мастера (JSON)");
        return 2;
    };
    let choices: setup::Choices = match std::fs::read_to_string(file).map_err(|e| e.to_string()).and_then(|text| {
        serde_json::from_str(&text).map_err(|e| e.to_string())
    }) {
        Ok(choices) => choices,
        Err(e) => {
            log!("{file}: {e}");
            return 2;
        }
    };
    println!("{}", serde_json::json!({ "check": setup::check_folder(&choices.data_dir) }));
    let emit: setup::Emit = Arc::new(|p| println!("{}", serde_json::to_string(&p).unwrap_or_default()));
    match tauri::async_runtime::block_on(setup::install(paths, version, &choices, &emit)) {
        Ok(()) => {
            let mut state = paths.state();
            state.setup_done = true;
            if let Err(e) = paths.save_state(&state) {
                log!("state.json: {e}");
                return 1;
            }
            println!("{}", serde_json::json!({ "done": true }));
            0
        }
        Err(e) => {
            log!("установка: {e}");
            1
        }
    }
}

fn main() {
    // TLS загрузок и обновлений — rustls с ring (как у tauri-plugin-updater)
    let _ = rustls::crypto::ring::default_provider().install_default();
    let args: Vec<String> = std::env::args().collect();
    let paths = Paths::new();
    log::init(paths.logs().join("app.log"));
    let context = tauri::generate_context!();
    let version = paths::amemo_version(&context.package_info().version.to_string());
    if let Some(i) = args.iter().position(|a| a == UNATTENDED) {
        std::process::exit(unattended(&paths, &version, args.get(i + 1).map(String::as_str)));
    }
    let background = args.iter().any(|a| a == BACKGROUND);
    let quit_only = args.iter().any(|a| a == QUIT);
    let service = Service::new(paths.clone());
    let app = tauri::Builder::default()
        // первым: второй экземпляр завершается до того, как что-то создаст
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if argv.iter().any(|a| a == QUIT) {
                quit(app);
            } else if !argv.iter().any(|a| a == BACKGROUND) {
                open_window(app);
            }
        }))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::all() & !StateFlags::VISIBLE)
                .build(),
        )
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, Some(vec![BACKGROUND])))
        .manage(App { paths, service, pause: Mutex::new(None) })
        .invoke_handler(tauri::generate_handler![
            setup::setup_defaults,
            setup::setup_check_folder,
            setup::setup_pick_folder,
            setup::setup_install,
            setup::setup_finish,
            app_start,
            app_resume,
        ])
        .setup(move |app| {
            if quit_only {
                std::process::exit(0); // другого экземпляра нет — останавливать нечего
            }
            log!("запуск {version}{}", if background { " в фоне" } else { "" });
            let handle = app.handle().clone();
            tray(&handle)?;
            follow_status(handle.clone());
            if configured(&handle) {
                handle.state::<App>().service.start();
            }
            if !background {
                show_main(&handle);
            }
            tauri::async_runtime::spawn(check_update(handle));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // мастер не пройден — закрытие завершает приложение; дальше окно только прячется
                if window.label() == MAIN && configured(window.app_handle()) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(context)
        .expect("amemo: приложение не запустилось");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<App>().service.stop(false);
        }
    });
}
