//! Новый комплект после обновления приложения (спецификация приложения для Windows, п. 6 и 11). Приложение версии N+1
//! запускается с комплектом N (`runtime\current`): прежде чем поднять фон, оно переводит amemo на свой комплект.
//!
//! 1. backup — `amemo backup create` прежним комплектом (база запущена на время дампа);
//! 2. download — комплект этой версии из релиза (продолжение с места, SHA-256), распаковка в `runtime\<версия>`;
//! 3. migrate — снимок кластера (`<данные>\pg` → `pg.before-update`, база остановлена) и amemo.toml, затем `amemo
//!    setup` новым комплектом: программы PostgreSQL из него, миграции; `runtime\current` — новая версия.
//!
//! Дальше фон поднимается как обычно. Служба ответила — `commit`: снимки и прежний комплект удаляются. Ошибка на
//! любом шаге — `rollback`: кластер и amemo.toml из снимков, `runtime\current` — прежний, и эта версия комплекта
//! больше не пробуется (`State::skipped_runtime`), пока не выйдет следующая. Логический дамп из шага 1 остаётся в
//! папке бэкапов при любом исходе.

use crate::{download, paths, paths::Paths, setup};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Stdio,
};

/// Начатый переход на новый комплект: чем закончить или как откатить.
pub struct Pending {
    pub version: String,
    old: PathBuf,
    cluster: PathBuf,
    snapshot: PathBuf,
    config: PathBuf,
    config_copy: PathBuf,
}

fn suffixed(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(suffix);
    PathBuf::from(name)
}

fn copy_dir(from: &Path, to: &Path) -> std::io::Result<()> {
    fs::create_dir_all(to)?;
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// `amemo …` из комплекта; ошибка — последние строки stderr или detail ответа JSON.
fn amemo(runtime: &Path, args: &[&str]) -> Result<serde_json::Value, String> {
    let output = setup::amemo(runtime)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("amemo {}: {e}", args.join(" ")))?;
    let reply: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap_or_default();
    if output.status.success() {
        return Ok(reply);
    }
    let detail = reply.get("detail").and_then(|d| d.as_str()).map(str::to_string).unwrap_or_else(|| {
        let text = String::from_utf8_lossy(&output.stderr);
        let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
        lines[lines.len().saturating_sub(3)..].join("\n")
    });
    Err(format!("amemo {}: {detail}", args.first().copied().unwrap_or("")))
}

/// Нужен ли переход: текущий комплект не этой версии и эту версию ещё не откатывали.
pub fn needed(paths: &Paths, version: &str) -> Option<PathBuf> {
    let old = paths.current()?;
    let name = old.file_name()?.to_string_lossy().into_owned();
    let skipped = paths.state().skipped_runtime;
    (name != version && skipped.as_deref() != Some(version)).then_some(old)
}

/// Шаги 1–3. `step` — для экрана запуска: backup, download, migrate.
pub fn prepare(paths: &Paths, version: &str, old: PathBuf, step: &dyn Fn(&str)) -> Result<Pending, String> {
    let cluster = PathBuf::from(paths::config_value("pg_data").ok_or("в amemo.toml нет pg_data")?);
    let data = cluster.parent().ok_or("pg_data без родительской папки")?.to_path_buf();
    let config = paths::config_file();
    let pending = Pending {
        version: version.to_string(),
        snapshot: suffixed(&cluster, ".before-update"),
        config_copy: suffixed(&config, ".before-update"),
        old,
        cluster,
        config,
    };
    crate::log!("переход на комплект {version} с {}", pending.old.display());

    step("backup");
    amemo(&pending.old, &["pg", "start", "--json"])?;
    let backup = amemo(&pending.old, &["backup", "create", "--json"]);
    let _ = amemo(&pending.old, &["pg", "stop", "--json"]);
    let backup = backup?;
    crate::log!("бэкап перед обновлением: {}", backup.get("manifest").or(backup.get("path")).unwrap_or(&backup));

    step("download");
    let runtime = paths.runtime(version);
    if !paths::complete(&runtime) {
        let base = setup::release_base(version);
        let downloads = paths.downloads();
        tauri::async_runtime::block_on(async {
            let client = download::client(version)?;
            let item = download::describe(&client, &base, &format!("amemo-runtime-{version}-windows-x64.zip")).await?;
            let archive = download::fetch(&client, &item, &downloads, &mut |_| {}).await?;
            download::unzip(&archive, &runtime)
        })?;
        let _ = fs::remove_dir_all(paths.downloads());
    }

    step("migrate");
    let migrated = (|| {
        let _ = fs::remove_dir_all(&pending.snapshot);
        copy_dir(&pending.cluster, &pending.snapshot)
            .map_err(|e| format!("снимок {}: {e}", pending.snapshot.display()))?;
        fs::write(pending.snapshot.join(SNAPSHOT_DONE), b"")
            .map_err(|e| format!("снимок {}: {e}", pending.snapshot.display()))?;
        fs::copy(&pending.config, &pending.config_copy)
            .map_err(|e| format!("{}: {e}", pending.config_copy.display()))?;
        let pg_bin = paths::pg_bin(&runtime).to_string_lossy().into_owned();
        let data = data.to_string_lossy().into_owned();
        amemo(&runtime, &["setup", "--pg-bin", &pg_bin, "--data", &data, "--no-auto-update", "--json"])?;
        paths.set_current(version).map_err(|e| format!("runtime\\current: {e}"))
    })();
    if let Err(e) = migrated {
        pending.rollback(paths, &e);
        return Err(e);
    }
    Ok(pending)
}

/// Метка снимка, скопированного целиком: только такой снимок заменяет кластер при откате.
const SNAPSHOT_DONE: &str = ".amemo-snapshot-complete";

impl Pending {
    /// Служба новой версии ответила: снимки и прежний комплект больше не нужны.
    pub fn commit(self, paths: &Paths) {
        let _ = fs::remove_dir_all(&self.snapshot);
        let _ = fs::remove_file(&self.config_copy);
        let mut state = paths.state();
        state.runtime = Some(self.version.clone());
        state.skipped_runtime = None;
        if let Err(e) = paths.save_state(&state) {
            crate::log!("state.json: {e}");
        }
        cleanup(paths);
        crate::log!("комплект {}: готово", self.version);
    }

    /// Вернуть кластер, настройки и прежний комплект; эту версию больше не пробовать.
    pub fn rollback(&self, paths: &Paths, why: &str) {
        crate::log!("комплект {}: откат — {why}", self.version);
        let new = paths.runtime(&self.version);
        if paths::complete(&new) {
            let _ = amemo(&new, &["pg", "stop", "--json"]);
        }
        if self.snapshot.join(SNAPSHOT_DONE).is_file() {
            let _ = fs::remove_dir_all(&self.cluster);
            match fs::rename(&self.snapshot, &self.cluster) {
                Ok(()) => {
                    let _ = fs::remove_file(self.cluster.join(SNAPSHOT_DONE));
                }
                Err(e) => crate::log!("откат кластера {}: {e}", self.cluster.display()),
            }
        } else {
            let _ = fs::remove_dir_all(&self.snapshot); // недокопированный снимок; кластер setup не трогал
        }
        if self.config_copy.is_file() {
            if let Err(e) = fs::rename(&self.config_copy, &self.config) {
                crate::log!("откат {}: {e}", self.config.display());
            }
        }
        if let Some(name) = self.old.file_name() {
            if let Err(e) = paths.set_current(&name.to_string_lossy()) {
                crate::log!("runtime\\current: {e}");
            }
        }
        let mut state = paths.state();
        state.skipped_runtime = Some(self.version.clone());
        if let Err(e) = paths.save_state(&state) {
            crate::log!("state.json: {e}");
        }
    }
}

/// Прежние комплекты: всё в `runtime\`, кроме текущего. Файлы, которые ещё держит процесс (сервер MCP агента,
/// запущенный до обновления), не удаляются — попытка повторяется при следующем запуске.
pub fn cleanup(paths: &Paths) {
    let Some(current) = paths.current() else { return };
    let Ok(entries) = fs::read_dir(paths.runtimes()) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() && path != current {
            match fs::remove_dir_all(&path) {
                Ok(()) => crate::log!("удалён прежний комплект {}", path.display()),
                Err(e) => crate::log!("прежний комплект {} пока занят: {e}", path.display()),
            }
        }
    }
}
