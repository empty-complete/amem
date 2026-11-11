//! Мастер первого запуска: команды моста `web/src/setup/bridge.ts` (setup_defaults, setup_check_folder,
//! setup_pick_folder, setup_install с событиями setup://progress, setup_finish) и сама установка
//! (спецификация приложения для Windows, п. 4–7):
//! 1. download — комплект и модель смыслового поиска из релиза этой версии (продолжение с места обрыва, SHA-256),
//!    распаковка комплекта в `runtime\<версия>`;
//! 2. database, store, search, ocr, agents — `amemo setup --progress` из комплекта: строки JSON его stderr и есть ход
//!    этих шагов.
//!
//! Повторная установка (кнопка «Повторить») продолжает с места: сверенные загрузки и распакованный комплект не
//! повторяются, `amemo setup` сам переиспользует кластер и настройки.

use crate::{download, paths, paths::Paths, winpath};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env, fs,
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Instant,
};
use tauri::{AppHandle, Emitter, Manager, State};

pub const RELEASES: &str = "https://github.com/empty-complete/amemo/releases/download";
pub const MODEL_ZIP: &str = "amemo-model-paraphrase-multilingual-MiniLM-L12-v2.zip";
/// комплект (~210 МБ) и модель (~210 МБ) в загрузках, распакованные (~0,8 ГБ) и запас под базу
const NEED: u64 = 1536 << 20;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Defaults {
    lang: String,
    data_dir: String,
    docs_dir: Option<String>,
    agents: Agents,
    version: String,
    /// "setup" — мастер; "start" — мастер уже пройден, экран запуска
    mode: &'static str,
}

#[derive(Serialize)]
struct Agents {
    claude: bool,
    codex: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderCheck {
    pub free: u64,
    pub need: u64,
    pub ansi_safe: bool,
    pub not_empty: bool,
    pub fallback: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Choices {
    pub lang: String,
    pub data_dir: String,
    pub docs_dir: Option<String>,
    #[serde(default)]
    pub ocr: Vec<String>,
    #[serde(default)]
    pub agents: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Progress {
    pub stage: String,
    pub state: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub received: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub total: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub rate: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub message: Option<String>,
}

impl Progress {
    fn new(stage: &str, state: &str) -> Self {
        Self { stage: stage.into(), state: state.into(), ..Default::default() }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Finish {
    pub desktop_shortcut: bool,
    pub autostart: bool,
}

pub fn version(app: &AppHandle) -> String {
    paths::amemo_version(&app.package_info().version.to_string())
}

fn on_path(names: &[&str]) -> bool {
    let Some(path) = env::var_os("PATH") else { return false };
    env::split_paths(&path).any(|dir| names.iter().any(|name| dir.join(name).is_file()))
}

/// Языки интерфейса amemo — ru и en: прежний выбор из amemo.toml, иначе язык Windows.
fn lang() -> String {
    match paths::config_value("lang").as_deref() {
        Some("ru") => "ru".into(),
        Some("en") => "en".into(),
        _ if winpath::prefers_russian() => "ru".into(),
        _ => "en".into(),
    }
}

pub fn ui_lang() -> String {
    lang()
}

#[tauri::command]
pub fn setup_defaults(app: AppHandle, state: State<'_, crate::App>) -> Defaults {
    let home = paths::home();
    // повторный мастер — папка прежней установки (кластер в <data>\pg)
    let data_dir = paths::config_value("pg_data")
        .and_then(|pg| Path::new(&pg).parent().map(Path::to_path_buf))
        .unwrap_or_else(|| home.join("amemo-data"));
    let appdata = env::var_os("APPDATA").map(PathBuf::from);
    let claude = home.join(".claude").is_dir()
        || appdata.as_ref().is_some_and(|a| a.join("Claude").is_dir())
        || on_path(&["claude.exe", "claude.cmd"]);
    let codex = home.join(".codex").is_dir() || on_path(&["codex.exe", "codex.cmd"]);
    let done = state.paths.state().setup_done && state.paths.current().is_some();
    Defaults {
        lang: lang(),
        data_dir: data_dir.to_string_lossy().into_owned(),
        docs_dir: dirs::document_dir().map(|d| d.to_string_lossy().into_owned()),
        agents: Agents { claude, codex },
        version: version(&app),
        mode: if done { "start" } else { "setup" },
    }
}

pub fn check_folder(path: &str) -> FolderCheck {
    let dir = PathBuf::from(path);
    let ansi_safe = winpath::postgres_safe(&dir);
    // прежняя установка amemo (кластер в <data>\pg) — не «чужие файлы»: setup её переиспользует
    let previous = dir.join("pg").join("PG_VERSION").is_file();
    let not_empty = !previous && fs::read_dir(&dir).map(|mut entries| entries.next().is_some()).unwrap_or(false);
    let drive = env::var("SystemDrive").unwrap_or_else(|_| "C:".into());
    FolderCheck {
        free: winpath::free_space(&dir).unwrap_or(0),
        need: NEED,
        ansi_safe,
        not_empty,
        fallback: (!ansi_safe).then(|| format!("{drive}\\amemo-data")),
    }
}

#[tauri::command]
pub fn setup_check_folder(path: String) -> FolderCheck {
    check_folder(&path)
}

#[tauri::command]
pub async fn setup_pick_folder(app: AppHandle, initial: Option<String>) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;

    let (tx, rx) = tokio::sync::oneshot::channel();
    let mut dialog = app.dialog().file();
    if let Some(start) = initial.as_deref().and_then(|p| winpath::existing_ancestor(Path::new(p))) {
        dialog = dialog.set_directory(start);
    }
    dialog.pick_folder(move |picked| {
        let _ = tx.send(picked.and_then(|p| p.into_path().ok()));
    });
    rx.await.ok().flatten().map(|p| p.to_string_lossy().into_owned())
}

/// Откуда качать файлы релиза: `AMEMO_RELEASE_BASE` (проверки CI — свой сервер) или страница релиза этой версии.
fn release_base(version: &str) -> String {
    match env::var("AMEMO_RELEASE_BASE").ok().filter(|v| !v.is_empty()) {
        Some(base) if base.ends_with('/') => base,
        Some(base) => format!("{base}/"),
        None => format!("{RELEASES}/v{version}/"),
    }
}

/// Скорость по последним ~3 секундам загрузки.
struct Rate {
    samples: VecDeque<(Instant, u64)>,
}

impl Rate {
    fn push(&mut self, received: u64) -> u64 {
        let now = Instant::now();
        self.samples.push_back((now, received));
        while self.samples.len() > 2 && now.duration_since(self.samples[0].0).as_secs_f64() > 3.0 {
            self.samples.pop_front();
        }
        let (start, from) = self.samples[0];
        let secs = now.duration_since(start).as_secs_f64();
        if secs < 0.2 {
            0
        } else {
            (received.saturating_sub(from) as f64 / secs) as u64
        }
    }
}

/// Куда отправлять ход: окно мастера (событие setup://progress) или вывод `--setup-unattended`.
pub type Emit = std::sync::Arc<dyn Fn(Progress) + Send + Sync>;

/// Шаг download: комплект распакован в `runtime\<версия>`, файлы модели — в возвращаемой папке.
async fn fetch_release(paths: &Paths, version: &str, emit: &Emit) -> Result<PathBuf, String> {
    let runtime = paths.runtime(version);
    let model = paths.downloads().join("model");
    let base = release_base(version);
    let client = download::client(version)?;
    let mut items = Vec::new();
    if !paths::complete(&runtime) {
        items.push(download::describe(&client, &base, &format!("amemo-runtime-{version}-windows-x64.zip")).await?);
    }
    if !model.join(".complete").is_file() {
        items.push(download::describe(&client, &base, MODEL_ZIP).await?);
    }
    let total: u64 = items.iter().map(|i| i.size).sum();
    let mut done = 0u64;
    let mut rate = Rate { samples: VecDeque::new() };
    let mut last = Instant::now().checked_sub(std::time::Duration::from_secs(1)).unwrap_or_else(Instant::now);
    for item in &items {
        let archive = {
            let mut report = |got: u64| {
                let received = done + got;
                let speed = rate.push(received);
                if last.elapsed().as_millis() >= 200 || got == item.size {
                    last = Instant::now();
                    emit(Progress {
                        received: Some(received),
                        total: Some(total),
                        rate: Some(speed),
                        ..Progress::new("download", "running")
                    });
                }
            };
            download::fetch(&client, item, &paths.downloads(), &mut report).await?
        };
        done += item.size;
        crate::log!("загружен {} ({} байт)", item.name, item.size);
        let target = if item.name == MODEL_ZIP { model.clone() } else { runtime.clone() };
        let name = item.name.clone();
        tauri::async_runtime::spawn_blocking(move || download::unzip(&archive, &target))
            .await
            .map_err(|e| format!("{name}: {e}"))??;
        if item.name == MODEL_ZIP {
            fs::write(model.join(".complete"), b"").map_err(|e| format!("{}: {e}", model.display()))?;
        }
    }
    if !paths::complete(&runtime) {
        return Err(format!("{}: комплект распакован не целиком", runtime.display()));
    }
    paths.set_current(version).map_err(|e| format!("runtime\\current: {e}"))?;
    Ok(model)
}

/// Команда amemo из комплекта: `python -I -X utf8 -m amemo.cli …`, без окна консоли и без Hugging Face.
pub fn amemo(runtime: &Path) -> Command {
    let mut command = Command::new(paths::python(runtime));
    command.args(["-I", "-X", "utf8", "-m", "amemo.cli"]);
    command.env("HF_HUB_OFFLINE", "1"); // модель смыслового поиска — из архива релиза, не с Hugging Face
    no_window(&mut command);
    command
}

pub fn no_window(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    #[cfg(not(windows))]
    let _ = command;
}

/// Шаги database…agents: `amemo setup --progress`; ход — строки JSON его stderr, остальное — в журнал и в текст
/// ошибки.
fn run_setup(paths: &Paths, runtime: &Path, model: &Path, choices: &Choices, emit: &Emit) -> Result<(), String> {
    let mut command = amemo(runtime);
    command
        .arg("setup")
        .arg("--pg-bin")
        .arg(paths::pg_bin(runtime))
        .arg("--data")
        .arg(&choices.data_dir)
        .args(["--lang", if choices.lang == "en" { "en" } else { "ru" }])
        .arg("--embed")
        .arg("--embed-models")
        .arg(model)
        .args(["--no-auto-update", "--progress"]);
    if let Some(docs) = choices.docs_dir.as_deref().filter(|d| !d.is_empty()) {
        command.arg("--docs").arg(docs);
    }
    if !choices.ocr.is_empty() {
        command.arg("--ocr").arg(choices.ocr.join(","));
    }
    let agents: Vec<&str> = choices
        .agents
        .iter()
        .filter_map(|a| match a.as_str() {
            "claude" => Some("claude-code"), // плагин приложения Claude — часть D6
            "codex" => Some("codex"),
            _ => None,
        })
        .collect();
    if !agents.is_empty() {
        command.arg("--agents").arg(agents.join(","));
    }
    crate::log!("установка: {:?}", command);
    let log_path = paths.logs().join("setup.log");
    crate::log::rotate(&log_path);
    let mut log = fs::OpenOptions::new().create(true).append(true).open(&log_path).ok();
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{}: {e}", paths::python(runtime).display()))?;
    let mut running: Option<String> = None;
    let mut tail: VecDeque<String> = VecDeque::new();
    if let Some(stderr) = child.stderr.take() {
        for line in BufReader::new(stderr).lines() {
            let Ok(line) = line else { break };
            if let Some(out) = log.as_mut() {
                use std::io::Write;
                let _ = writeln!(out, "{} {line}", crate::log::stamp());
            }
            if let Ok(step) = serde_json::from_str::<Progress>(&line) {
                running = (step.state == "running").then(|| step.stage.clone());
                emit(step);
                continue;
            }
            if !line.trim().is_empty() {
                tail.push_back(line);
                if tail.len() > 6 {
                    tail.pop_front();
                }
            }
        }
    }
    let status = child.wait().map_err(|e| format!("amemo setup: {e}"))?;
    if status.success() {
        return Ok(());
    }
    let stage = running.unwrap_or_else(|| "database".into());
    let detail = tail.into_iter().collect::<Vec<_>>().join("\n");
    let message = if detail.is_empty() {
        format!("amemo setup: код {}; журнал — {}", status.code().unwrap_or(-1), log_path.display())
    } else {
        format!("{detail}\nЖурнал — {}", log_path.display())
    };
    emit(Progress { message: Some(message.clone()), ..Progress::new(&stage, "failed") });
    Err(message)
}

/// Установка целиком: download, затем `amemo setup`. Ошибка шага уже отправлена событием failed.
pub async fn install(paths: &Paths, version: &str, choices: &Choices, emit: &Emit) -> Result<(), String> {
    crate::log!("установка {version}: данные {}, язык {}", choices.data_dir, choices.lang);
    emit(Progress::new("download", "running"));
    let model = match fetch_release(paths, version, emit).await {
        Ok(model) => model,
        Err(message) => {
            crate::log!("загрузка: {message}");
            emit(Progress { message: Some(message.clone()), ..Progress::new("download", "failed") });
            return Err(message);
        }
    };
    emit(Progress::new("download", "done"));
    let runtime = paths.runtime(version);
    let (paths_, choices_, emit_) = (paths.clone(), choices.clone(), emit.clone());
    tauri::async_runtime::spawn_blocking(move || run_setup(&paths_, &runtime, &model, &choices_, &emit_))
        .await
        .map_err(|e| format!("amemo setup: {e}"))??;
    let mut state = paths.state();
    state.runtime = Some(version.to_string());
    paths.save_state(&state).map_err(|e| format!("state.json: {e}"))?;
    let _ = fs::remove_dir_all(paths.downloads()); // ~0,4 ГБ загрузок больше не нужны
    crate::log!("установка {version}: готово");
    Ok(())
}

#[tauri::command]
pub async fn setup_install(app: AppHandle, choices: Choices) -> Result<(), String> {
    let paths = app.state::<crate::App>().paths.clone();
    let version = version(&app);
    let emit: Emit = std::sync::Arc::new(move |p: Progress| {
        let _ = app.emit("setup://progress", p);
    });
    install(&paths, &version, &choices, &emit).await
}

fn shortcut(enabled: bool) -> Result<(), String> {
    let Some(desktop) = dirs::desktop_dir() else { return Ok(()) };
    let link = desktop.join("amemo.lnk");
    if !enabled {
        if link.exists() {
            fs::remove_file(&link).map_err(|e| format!("{}: {e}", link.display()))?;
        }
        return Ok(());
    }
    if link.exists() {
        return Ok(()); // его кладёт NSIS
    }
    let exe = env::current_exe().map_err(|e| e.to_string())?;
    // ярлык — через WScript.Shell; пути — переменными окружения, без подстановки в текст команды
    let mut command = Command::new("powershell");
    command
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:AMEMO_LNK); \
             $s.TargetPath = $env:AMEMO_EXE; $s.WorkingDirectory = $env:AMEMO_DIR; $s.Save()",
        ])
        .env("AMEMO_LNK", &link)
        .env("AMEMO_EXE", &exe)
        .env("AMEMO_DIR", exe.parent().unwrap_or(Path::new(".")));
    no_window(&mut command);
    let status = command.status().map_err(|e| format!("ярлык: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("ярлык {}: powershell, код {}", link.display(), status.code().unwrap_or(-1)))
    }
}

#[tauri::command]
pub async fn setup_finish(app: AppHandle, options: Finish) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;

    if let Err(e) = shortcut(options.desktop_shortcut) {
        crate::log!("{e}"); // ярлык — не повод останавливать запуск amemo
    }
    let autolaunch = app.autolaunch();
    let switched = if options.autostart { autolaunch.enable() } else { autolaunch.disable() };
    if let Err(e) = switched {
        crate::log!("автозапуск: {e}");
    }
    let state = app.state::<crate::App>();
    let mut saved = state.paths.state();
    saved.setup_done = true;
    state.paths.save_state(&saved).map_err(|e| format!("state.json: {e}"))?;
    crate::tray_refresh(&app);
    crate::open_service(&app, false).await
}
