//! Загрузка файлов релиза: продолжение с места обрыва (HTTP Range), сверка SHA-256 из файла `<имя>.sha256` рядом
//! (формат sha256sum, его пишет `tools/runtime.py`), распаковка zip во временную папку и переименование.

use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

pub struct Item {
    pub name: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
}

pub fn client(version: &str) -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent(format!("amemo-desktop/{version}"))
        .connect_timeout(Duration::from_secs(30))
        .read_timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| format!("загрузка: {e}"))
}

/// Адрес, сумма и размер файла релиза.
pub async fn describe(client: &reqwest::Client, base: &str, name: &str) -> Result<Item, String> {
    let url = format!("{base}{name}");
    let sums = client
        .get(format!("{url}.sha256"))
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|e| format!("{url}.sha256: {e}"))?
        .text()
        .await
        .map_err(|e| format!("{url}.sha256: {e}"))?;
    let sha256 = sums.split_whitespace().next().unwrap_or("").to_ascii_lowercase();
    if sha256.len() != 64 || !sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(format!("{url}.sha256: нет суммы SHA-256"));
    }
    let head = client
        .head(&url)
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|e| format!("{url}: {e}"))?;
    // content_length() у ответа на HEAD — размер пустого тела, поэтому заголовок
    let size = head
        .headers()
        .get(reqwest::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse().ok())
        .ok_or_else(|| format!("{url}: сервер не сообщил размер"))?;
    Ok(Item { name: name.to_string(), url, sha256, size })
}

pub fn sha256(path: &Path) -> std::io::Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        digest.update(&buffer[..n]);
    }
    Ok(digest.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

fn part_of(target: &Path) -> PathBuf {
    let mut part = target.as_os_str().to_owned();
    part.push(".part");
    PathBuf::from(part)
}

/// Файл в `dir`; `received(n)` — сколько байт уже есть (вызывается по ходу). Уже скачанный и сверенный файл не
/// качается заново; оборванный продолжается. Три попытки на сетевые ошибки.
pub async fn fetch(
    client: &reqwest::Client,
    item: &Item,
    dir: &Path,
    received: &mut (dyn FnMut(u64) + Send),
) -> Result<PathBuf, String> {
    fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let target = dir.join(&item.name);
    if target.is_file() && sha256(&target).ok().as_deref() == Some(item.sha256.as_str()) {
        received(item.size);
        return Ok(target);
    }
    let part = part_of(&target);
    let mut last = String::new();
    for attempt in 1..=3 {
        match fetch_once(client, item, &part, received).await {
            Ok(()) => {
                let got = sha256(&part).map_err(|e| format!("{}: {e}", part.display()))?;
                if got != item.sha256 {
                    let _ = fs::remove_file(&part);
                    return Err(format!("{}: SHA-256 {got}, ожидалась {} — файл повреждён", item.name, item.sha256));
                }
                fs::rename(&part, &target).map_err(|e| format!("{}: {e}", target.display()))?;
                return Ok(target);
            }
            Err(e) => {
                crate::log!("{}: попытка {attempt}: {e}", item.name);
                last = e;
                tokio::time::sleep(Duration::from_secs(2 * attempt)).await;
            }
        }
    }
    Err(format!("{}: {last}", item.url))
}

async fn fetch_once(
    client: &reqwest::Client,
    item: &Item,
    part: &Path,
    received: &mut (dyn FnMut(u64) + Send),
) -> Result<(), String> {
    let mut have = fs::metadata(part).map(|m| m.len()).unwrap_or(0);
    if have > item.size {
        have = 0;
    }
    if have == item.size && have > 0 {
        return Ok(());
    }
    let mut request = client.get(&item.url);
    if have > 0 {
        request = request.header(reqwest::header::RANGE, format!("bytes={have}-"));
    }
    let mut response = request.send().await.map_err(|e| e.to_string())?;
    let status = response.status();
    let append = if status == reqwest::StatusCode::PARTIAL_CONTENT {
        true
    } else if status.is_success() {
        have = 0; // сервер не умеет Range — с начала
        false
    } else {
        return Err(format!("HTTP {status}"));
    };
    let mut out = OpenOptions::new()
        .create(true)
        .write(true)
        .append(append)
        .truncate(!append)
        .open(part)
        .map_err(|e| format!("{}: {e}", part.display()))?;
    received(have);
    while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
        out.write_all(&chunk).map_err(|e| format!("{}: {e}", part.display()))?;
        have += chunk.len() as u64;
        received(have);
    }
    out.sync_all().map_err(|e| format!("{}: {e}", part.display()))?;
    if have != item.size {
        return Err(format!("получено {have} байт из {}", item.size));
    }
    Ok(())
}

/// Архив в папку `target`: распаковка рядом во временную `<target>.partial`, затем переименование — наполовину
/// распакованной папки под настоящим именем не бывает.
pub fn unzip(archive: &Path, target: &Path) -> Result<(), String> {
    let mut partial = target.as_os_str().to_owned();
    partial.push(".partial");
    let partial = PathBuf::from(partial);
    let _ = fs::remove_dir_all(&partial);
    fs::create_dir_all(&partial).map_err(|e| format!("{}: {e}", partial.display()))?;
    let file = File::open(archive).map_err(|e| format!("{}: {e}", archive.display()))?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| format!("{}: {e}", archive.display()))?;
    zip.extract(&partial).map_err(|e| format!("{}: распаковка: {e}", archive.display()))?;
    if target.exists() {
        fs::remove_dir_all(target).map_err(|e| format!("{}: {e}", target.display()))?;
    }
    fs::rename(&partial, target).map_err(|e| format!("{}: {e}", target.display()))
}
