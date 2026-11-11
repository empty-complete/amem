//! `%LOCALAPPDATA%\amemo\bin\amemo.exe` — постоянный путь к amemo для агентов и терминала (спецификация приложения
//! для Windows, п. 10): сервер MCP приложения Claude, хуки и Codex вызывают его, а он — amemo из текущей версии
//! комплекта (`runtime\current` рядом с `bin\`), с теми же аргументами, вводом-выводом и кодом выхода. Обновление
//! комплекта меняет только `runtime\current` — подключения агентов не устаревают.
//!
//! Приложение консольное (в отличие от окна amemo): в терминале видно, что печатает amemo.

use std::{
    env, fs,
    path::{Path, PathBuf},
    process::{exit, Command},
};

fn runtime(root: &Path) -> Result<PathBuf, String> {
    let current = root.join("runtime").join("current");
    let version = fs::read_to_string(&current)
        .map_err(|e| format!("{}: {e} — amemo не установлен; запустите приложение amemo", current.display()))?;
    let dir = root.join("runtime").join(version.trim());
    let python = dir.join("python").join("python.exe");
    if !python.is_file() {
        return Err(format!("нет {}: комплект amemo повреждён; запустите приложение amemo", python.display()));
    }
    Ok(python)
}

fn main() {
    let exe = env::current_exe().unwrap_or_default();
    // bin\amemo.exe → корень приложения
    let root = exe.parent().and_then(Path::parent).map(Path::to_path_buf).unwrap_or_default();
    let python = match runtime(&root) {
        Ok(python) => python,
        Err(message) => {
            eprintln!("amemo: {message}");
            exit(1);
        }
    };
    // -I: без переменных PYTHON* и пользовательских site-packages; -X utf8: ввод-вывод в UTF-8 (сервер MCP)
    let status = Command::new(&python)
        .args(["-I", "-X", "utf8", "-m", "amemo.cli"])
        .args(env::args_os().skip(1))
        .env("HF_HUB_OFFLINE", "1") // модель смыслового поиска — из архива релиза (приложение), не с Hugging Face
        .status();
    match status {
        Ok(status) => exit(status.code().unwrap_or(1)),
        Err(e) => {
            eprintln!("amemo: {}: {e}", python.display());
            exit(1);
        }
    }
}
