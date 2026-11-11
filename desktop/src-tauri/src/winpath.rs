//! Пути Windows для программ PostgreSQL и место на диске.
//!
//! Программы PostgreSQL в Windows открывают файлы ANSI-функциями: символ вне кодовой страницы ANSI системы (кириллица
//! в английской Windows) становится «?», и initdb не находит даже себя. amemo передаёт такие пути короткими именами
//! 8.3 (`amemo/localpg.py`, `native`) — мастер заранее проверяет, что для выбранной папки это получится, и иначе
//! предлагает запасную (спецификация, п. 4 и «Риски»).

use std::path::{Path, PathBuf};

#[cfg(windows)]
mod sys {
    use std::{ffi::OsStr, os::windows::ffi::OsStrExt, path::Path, ptr};
    use windows_sys::Win32::{
        Globalization::{GetUserDefaultUILanguage, WideCharToMultiByte, CP_ACP, WC_NO_BEST_FIT_CHARS},
        Storage::FileSystem::{GetDiskFreeSpaceExW, GetShortPathNameW},
    };

    fn wide(text: &OsStr) -> Vec<u16> {
        text.encode_wide().chain(std::iter::once(0)).collect()
    }

    /// Как `text.encode("mbcs", "strict")` в Python: без «лучшего похожего» символа и без символа по умолчанию.
    pub fn ansi(text: &str) -> bool {
        let units: Vec<u16> = text.encode_utf16().collect();
        if units.is_empty() {
            return true;
        }
        let mut used = 0;
        let size = unsafe {
            WideCharToMultiByte(
                CP_ACP,
                WC_NO_BEST_FIT_CHARS,
                units.as_ptr(),
                units.len() as i32,
                ptr::null_mut(),
                0,
                ptr::null(),
                &mut used,
            )
        };
        size > 0 && used == 0
    }

    pub fn short(path: &Path) -> Option<String> {
        let long = wide(path.as_os_str());
        let size = unsafe { GetShortPathNameW(long.as_ptr(), ptr::null_mut(), 0) };
        if size == 0 {
            return None;
        }
        let mut buffer = vec![0u16; size as usize];
        let got = unsafe { GetShortPathNameW(long.as_ptr(), buffer.as_mut_ptr(), size) };
        (got > 0 && got < size).then(|| String::from_utf16_lossy(&buffer[..got as usize]))
    }

    pub fn free_space(path: &Path) -> Option<u64> {
        let dir = wide(path.as_os_str());
        let mut free = 0u64;
        let ok = unsafe { GetDiskFreeSpaceExW(dir.as_ptr(), &mut free, ptr::null_mut(), ptr::null_mut()) };
        (ok != 0).then_some(free)
    }

    /// Основной язык интерфейса Windows (LANGID & 0x3ff).
    pub fn ui_language() -> u16 {
        unsafe { GetUserDefaultUILanguage() } & 0x3ff
    }
}

#[cfg(not(windows))]
mod sys {
    //! Приложение собирается только для Windows; заглушки — чтобы код проверялся и на других системах.
    use std::path::Path;

    pub fn ansi(text: &str) -> bool {
        text.is_ascii()
    }

    pub fn short(path: &Path) -> Option<String> {
        Some(path.to_string_lossy().into_owned())
    }

    pub fn free_space(_path: &Path) -> Option<u64> {
        None
    }

    pub fn ui_language() -> u16 {
        0x09
    }
}

/// Ближайшая существующая папка на пути (сам путь, если он есть).
pub fn existing_ancestor(path: &Path) -> Option<PathBuf> {
    path.ancestors().find(|p| p.is_dir()).map(Path::to_path_buf)
}

/// Свободно на томе папки, байт.
pub fn free_space(path: &Path) -> Option<u64> {
    sys::free_space(&existing_ancestor(path)?)
}

/// Русский интерфейс Windows (и близкие: украинский, белорусский, казахский) — мастер по-русски.
pub fn prefers_russian() -> bool {
    matches!(sys::ui_language(), 0x19 | 0x22 | 0x23 | 0x3f)
}

/// Откроют ли программы PostgreSQL этот путь: сам он в кодовой странице ANSI или у него есть короткое имя из
/// символов ANSI. Короткое имя есть только у существующей папки, поэтому недостающие папки создаются на время
/// проверки и убираются (только пустые и только созданные здесь).
pub fn postgres_safe(path: &Path) -> bool {
    if sys::ansi(&path.to_string_lossy()) {
        return true;
    }
    let missing: Vec<PathBuf> = path.ancestors().take_while(|p| !p.exists()).map(Path::to_path_buf).collect();
    if std::fs::create_dir_all(path).is_err() {
        return false;
    }
    let ok = sys::short(path).is_some_and(|short| sys::ansi(&short));
    for dir in &missing {
        let _ = std::fs::remove_dir(dir); // от глубокой к верхней; непустую remove_dir не тронет
    }
    ok
}
