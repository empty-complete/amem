/// Команды приложения — только по разрешениям: мастеру и экрану запуска (capabilities/main.json, свои страницы
/// приложения) — да, странице службы на 127.0.0.1 (capabilities/service.json) — нет.
const COMMANDS: &[&str] = &[
    "setup_defaults",
    "setup_check_folder",
    "setup_pick_folder",
    "setup_install",
    "setup_finish",
    "app_start",
    "app_resume",
];

fn main() {
    // версия amemo (PEP 440) для имён файлов релиза — paths::amemo_version
    println!("cargo:rerun-if-env-changed=AMEMO_VERSION");
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("tauri-build");
}
