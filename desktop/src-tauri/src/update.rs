//! Обновления приложения (спецификация приложения для Windows, п. 3 и 11): updater Tauri читает манифест
//! `latest.json` (стабильный канал) или `latest-pre.json` (предварительный — у предварительной версии приложения) при
//! запуске и раз в 6 часов. Нашёл новую версию — ставит её сразу: установщик NSIS в режиме passive (маленькое окно
//! с ходом), приложение перед этим останавливает службу и базу, а установщик запускает новую версию с теми же
//! аргументами (`--background` остаётся фоном). Новая версия при запуске переходит на свой комплект (upgrade.rs).
//!
//! - Пока мастер не пройден, обновление проверяется один раз сразу: старый установщик не поставит старую версию.
//!   Установка, начатая в мастере, обновление не прерывает — оно подождёт следующей проверки.
//! - Выключатель — пункт значка «Обновлять автоматически» (`State::no_auto_update`).
//! - Манифесты лежат в постоянном релизе `updates` (их обновляет workflow релиза): `releases/latest/download/…` не
//!   видит предварительные релизы. `AMEMO_UPDATE_URL` — другой адрес манифеста (проверки CI).

use crate::{log, App};
use std::{
    sync::atomic::Ordering,
    time::Duration,
};
use tauri::{AppHandle, Manager};
use tauri_plugin_updater::UpdaterExt;

pub const MANIFESTS: &str = "https://github.com/empty-complete/amemo/releases/download/updates";
const EVERY: Duration = Duration::from_secs(6 * 3600);

/// Манифест канала этой версии приложения.
pub fn endpoint(app_version: &str) -> String {
    if let Some(url) = std::env::var("AMEMO_UPDATE_URL").ok().filter(|v| !v.is_empty()) {
        return url;
    }
    let file = if app_version.contains('-') { "latest-pre.json" } else { "latest.json" };
    format!("{MANIFESTS}/{file}")
}

/// Проверить и, если есть новая версия, поставить её (приложение завершится — установщик запустит новую).
pub async fn check(app: &AppHandle) -> Result<Option<String>, String> {
    let version = app.package_info().version.to_string();
    let url: tauri::Url = endpoint(&version).parse().map_err(|e| format!("адрес обновлений: {e}"))?;
    let service = app.state::<App>().service.clone();
    let updater = app
        .updater_builder()
        .endpoints(vec![url])
        .map_err(|e| e.to_string())?
        .on_before_exit(move || {
            log!("установка обновления: остановка фона");
            service.stop(false);
        })
        .build()
        .map_err(|e| e.to_string())?;
    let Some(update) = updater.check().await.map_err(|e| e.to_string())? else { return Ok(None) };
    let found = update.version.clone();
    let state = app.state::<App>();
    if state.paths.state().no_auto_update {
        log!("доступна версия {found}; обновления выключены");
        return Ok(Some(found));
    }
    if state.installing.load(Ordering::SeqCst) {
        log!("доступна версия {found}; идёт установка мастером — обновление при следующей проверке");
        return Ok(Some(found));
    }
    log!("обновление до {found}: загрузка");
    update
        .download_and_install(|_, _| {}, || log!("обновление загружено, установка"))
        .await
        .map_err(|e| format!("обновление до {found}: {e}"))?;
    Ok(Some(found)) // в Windows сюда не доходит: приложение завершается перед установкой
}

/// Проверка при запуске (через 10 с — окно и фон успевают подняться) и раз в 6 часов.
pub fn schedule(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_secs(10)).await;
        loop {
            if let Err(e) = check(&app).await {
                log!("проверка обновлений не удалась: {e}");
            }
            tokio::time::sleep(EVERY).await;
        }
    });
}
