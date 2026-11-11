//! Журнал приложения — `logs\app.log` в папке приложения (окна консоли у приложения нет). Больше 5 МБ — прежний
//! уходит в `app.log.1`.

use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
    time::{SystemTime, UNIX_EPOCH},
};

const MAX: u64 = 5 << 20;

static FILE: OnceLock<Mutex<PathBuf>> = OnceLock::new();

/// Файл больше предела — в `<имя>.1` (прежний `.1` пропадает).
pub fn rotate(path: &Path) {
    if fs::metadata(path).map(|m| m.len() > MAX).unwrap_or(false) {
        let mut old = path.as_os_str().to_owned();
        old.push(".1");
        let _ = fs::rename(path, PathBuf::from(old));
    }
}

pub fn init(path: PathBuf) {
    if let Some(dir) = path.parent() {
        let _ = fs::create_dir_all(dir);
    }
    rotate(&path);
    let _ = FILE.set(Mutex::new(path));
}

/// Время UTC `ГГГГ-ММ-ДД чч:мм:сс` без сторонних библиотек (алгоритм civil_from_days).
pub fn stamp() -> String {
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) as i64;
    let (days, rest) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02} {:02}:{:02}:{:02}", rest / 3600, rest / 60 % 60, rest % 60)
}

pub fn line(message: &str) {
    eprintln!("amemo: {message}");
    if let Some(file) = FILE.get() {
        if let Ok(path) = file.lock() {
            if let Ok(mut out) = OpenOptions::new().create(true).append(true).open(&*path) {
                let _ = writeln!(out, "{} {message}", stamp());
            }
        }
    }
}

#[macro_export]
macro_rules! log {
    ($($arg:tt)*) => { $crate::log::line(&format!($($arg)*)) };
}
