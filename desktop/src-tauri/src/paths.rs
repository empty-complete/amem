//! Где что лежит (спецификация приложения для Windows, п. 6 и 10). Корень — папка приложения, куда его поставил
//! NSIS (`%LOCALAPPDATA%\amemo`):
//! - `runtime\<версия>\` — распакованный комплект (PostgreSQL, Python с amemo), `runtime\current` — имя текущей;
//! - `bin\amemo.exe` — запускатель текущего комплекта (desktop/launcher);
//! - `downloads\` — загрузки мастера, пока идёт установка; `logs\` — журналы; `state.json` — состояние приложения.
//!
//! Настройки amemo (`amemo.toml`) — там же, где их ищет amemo: `AMEMO_CONFIG` или `%USERPROFILE%\.config\amemo`.

use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug)]
pub struct Paths {
    pub root: PathBuf,
}

/// Состояние приложения между запусками.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct State {
    /// версия комплекта, с которой мастер завершился
    #[serde(default)]
    pub runtime: Option<String>,
    /// мастер пройден: при запуске — фон и окно amemo, а не мастер
    #[serde(default)]
    pub setup_done: bool,
    /// zip плагина для приложения Claude, если в мастере выбран Claude: тогда приложение следит, когда плагин из
    /// аккаунта появится в Claude Code, и снимает прямую установку (`amemo install claude-code --unless-synced`)
    #[serde(default)]
    pub plugin: Option<String>,
}

impl Paths {
    /// Корень — папка программы; `AMEMO_APP_HOME` — для проверок.
    pub fn new() -> Self {
        let root = env::var_os("AMEMO_APP_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .or_else(|| env::current_exe().ok().and_then(|exe| exe.parent().map(Path::to_path_buf)))
            .unwrap_or_else(|| PathBuf::from("."));
        Self { root }
    }

    pub fn runtimes(&self) -> PathBuf {
        self.root.join("runtime")
    }

    pub fn runtime(&self, version: &str) -> PathBuf {
        self.runtimes().join(version)
    }

    /// Текущий комплект, если он распакован целиком.
    pub fn current(&self) -> Option<PathBuf> {
        let version = fs::read_to_string(self.runtimes().join("current")).ok()?;
        let dir = self.runtime(version.trim());
        complete(&dir).then_some(dir)
    }

    pub fn set_current(&self, version: &str) -> std::io::Result<()> {
        write_atomic(&self.runtimes().join("current"), version.as_bytes())
    }

    pub fn downloads(&self) -> PathBuf {
        self.root.join("downloads")
    }

    pub fn logs(&self) -> PathBuf {
        self.root.join("logs")
    }

    fn state_file(&self) -> PathBuf {
        self.root.join("state.json")
    }

    pub fn state(&self) -> State {
        fs::read(self.state_file()).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
    }

    pub fn save_state(&self, state: &State) -> std::io::Result<()> {
        let body = serde_json::to_vec_pretty(state).map_err(std::io::Error::other)?;
        write_atomic(&self.state_file(), &body)
    }
}

/// Комплект распакован целиком: распаковка идёт во временную папку и переименовывается в конце, а эти файлы — его
/// части, без которых amemo не запустится.
pub fn complete(runtime: &Path) -> bool {
    runtime.join("runtime.json").is_file() && python(runtime).is_file() && pg_bin(runtime).join("pg_ctl.exe").is_file()
}

pub fn python(runtime: &Path) -> PathBuf {
    runtime.join("python").join("python.exe")
}

/// Запускатель `bin\amemo.exe` для комплекта `runtime\<версия>` — постоянный путь к amemo для агентов.
pub fn launcher(runtime: &Path) -> Option<PathBuf> {
    let root = runtime.parent()?.parent()?;
    let exe = root.join("bin").join("amemo.exe");
    exe.is_file().then_some(exe)
}

pub fn pg_bin(runtime: &Path) -> PathBuf {
    runtime.join("pgsql").join("bin")
}

pub fn write_atomic(path: &Path, body: &[u8]) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    fs::write(&tmp, body)?;
    fs::rename(&tmp, path)
}

pub fn home() -> PathBuf {
    env::var_os("USERPROFILE")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(dirs::home_dir)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// amemo.toml — как его ищет amemo (`amemo/cli/commands/local.py`, `_config_path`).
pub fn config_file() -> PathBuf {
    match env::var_os("AMEMO_CONFIG").filter(|v| !v.is_empty()) {
        Some(path) => PathBuf::from(path),
        None => home().join(".config").join("amemo").join("amemo.toml"),
    }
}

/// Значение верхнего уровня из amemo.toml. Файл пишет `amemo setup`: `ключ = значение`, строки — в кавычках JSON
/// (допустимая базовая строка TOML). Полный разбор TOML приложению не нужен: оно читает только lang, port, pg_data.
pub fn config_value(key: &str) -> Option<String> {
    let text = fs::read_to_string(config_file()).ok()?;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            break; // дальше — таблицы, не верхний уровень
        }
        let Some((name, value)) = line.split_once('=') else { continue };
        if name.trim() != key {
            continue;
        }
        let value = value.trim();
        return if value.starts_with('"') {
            serde_json::from_str::<String>(value).ok()
        } else {
            Some(value.split('#').next().unwrap_or("").trim().to_string())
        };
    }
    None
}

/// Версия amemo (PEP 440, как в именах файлов релиза): её задаёт сборка (`AMEMO_VERSION`, из amemo/__init__.py), а
/// без неё — обратное преобразование semver приложения (`tools/release.py semver`): 0.1.0-alpha.2 → 0.1.0a2.
pub fn amemo_version(app_version: &str) -> String {
    if let Some(version) = option_env!("AMEMO_VERSION").filter(|v| !v.is_empty()) {
        return version.to_string();
    }
    match app_version.split_once('-') {
        None => app_version.to_string(),
        Some((core, pre)) => {
            let (kind, number) = pre.split_once('.').unwrap_or((pre, "0"));
            let tag = match kind {
                "alpha" => "a",
                "beta" => "b",
                _ => "rc",
            };
            format!("{core}{tag}{number}")
        }
    }
}
