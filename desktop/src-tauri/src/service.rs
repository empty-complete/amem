//! Фон amemo (спецификация приложения для Windows, п. 9): PostgreSQL (`amemo pg start`, кластер из настроек
//! `amemo setup`) и служба `amemo serve` — дочерние процессы из текущего комплекта.
//!
//! - Запуск: кластер, затем служба; готово, когда `/health` службы отвечает 200. Служба, которая уже отвечает (её
//!   оставил прежний запуск приложения), переиспользуется.
//! - Слежение: служба завершилась сама — перезапуск (кластер — тоже, если он упал); больше трёх раз за 10 минут —
//!   ошибка, которую показывает экран запуска.
//! - Пауза и выход: служба завершается, кластер останавливается (`amemo pg stop`).
//!
//! - Обновление: комплект не той версии, что приложение, — сначала переход на свой (upgrade.rs, Status::Updating);
//!   служба нового комплекта не поднялась — откат на прежний и запуск с ним.
//!
//! Вывод службы — `logs\serve.log`.

use crate::{paths, paths::Paths, setup, upgrade};
use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    process::{Child, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tokio::sync::watch;

pub const DEFAULT_PORT: u16 = 8767; // amemo/settings.py DEFAULT_PORT

#[derive(Clone, Debug, PartialEq)]
pub enum Status {
    Stopped,
    Starting,
    /// переход на комплект новой версии: шаг backup, download или migrate
    Updating(String),
    Ready,
    Failed(String),
    Paused,
}

pub struct Service {
    paths: Paths,
    /// версия amemo этого приложения — версия его комплекта
    version: String,
    status: watch::Sender<Status>,
    child: Mutex<Option<Child>>,
    /// запуск или остановка идёт: второй не начинается, слежение не вмешивается
    busy: Mutex<()>,
    watching: AtomicBool,
    restarts: Mutex<Vec<Instant>>,
}

impl Service {
    pub fn new(paths: Paths, version: String) -> Arc<Self> {
        Arc::new(Self {
            paths,
            version,
            status: watch::channel(Status::Stopped).0,
            child: Mutex::new(None),
            busy: Mutex::new(()),
            watching: AtomicBool::new(false),
            restarts: Mutex::new(Vec::new()),
        })
    }

    pub fn status(&self) -> Status {
        self.status.borrow().clone()
    }

    pub fn subscribe(&self) -> watch::Receiver<Status> {
        self.status.subscribe()
    }

    fn set(&self, status: Status) {
        crate::log!("фон: {status:?}");
        self.status.send_replace(status);
    }

    pub fn port() -> u16 {
        paths::config_value("port").and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT)
    }

    pub fn url() -> String {
        format!("http://127.0.0.1:{}/ui/", Self::port())
    }

    /// Запустить в фоне (не ждёт). Уже запущенный или запускающийся — ничего.
    pub fn start(self: &Arc<Self>) {
        if matches!(self.status(), Status::Starting | Status::Updating(_) | Status::Ready) {
            return;
        }
        self.set(Status::Starting);
        let me = self.clone();
        thread::spawn(move || {
            let _busy = me.busy.lock().unwrap_or_else(|e| e.into_inner());
            match me.bring_up() {
                Ok(()) => me.set(Status::Ready),
                Err(e) => me.set(Status::Failed(e)),
            }
            drop(_busy);
            me.watch();
        });
    }

    /// Переход на свой комплект, если нужен, затем фон; служба нового комплекта не поднялась — откат и запуск
    /// с прежним.
    fn bring_up(&self) -> Result<(), String> {
        let pending = upgrade::needed(&self.paths, &self.version).and_then(|old| {
            match upgrade::prepare(&self.paths, &self.version, old, &|step| self.set(Status::Updating(step.into()))) {
                Ok(pending) => Some(pending),
                Err(e) => {
                    crate::log!("переход на комплект {}: {e}", self.version);
                    None
                }
            }
        });
        if !matches!(self.status(), Status::Starting) {
            self.set(Status::Starting);
        }
        match (self.run_current(), pending) {
            (Ok(()), Some(pending)) => {
                pending.commit(&self.paths);
                Ok(())
            }
            (Ok(()), None) => {
                upgrade::cleanup(&self.paths); // прежний комплект, который был занят при прошлом переходе
                Ok(())
            }
            (Err(e), Some(pending)) => {
                if let Some(mut child) = self.child.lock().unwrap_or_else(|e| e.into_inner()).take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                pending.rollback(&self.paths, &e);
                self.run_current()
            }
            (Err(e), None) => Err(e),
        }
    }

    /// PostgreSQL и служба текущего комплекта.
    fn run_current(&self) -> Result<(), String> {
        let runtime = self
            .paths
            .current()
            .ok_or("комплект amemo не найден или повреждён — запустите установку заново")?;
        pg(&runtime, "start")?;
        let port = Self::port();
        if health(port) {
            crate::log!("служба на порту {port} уже отвечает — используется она");
            return Ok(());
        }
        let log_path = self.paths.logs().join("serve.log");
        crate::log::rotate(&log_path);
        let _ = fs::create_dir_all(self.paths.logs());
        let out = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("{}: {e}", log_path.display()))?;
        let err = out.try_clone().map_err(|e| format!("{}: {e}", log_path.display()))?;
        let mut command = setup::amemo(&runtime);
        command.arg("serve").stdin(Stdio::null()).stdout(out).stderr(err);
        let child = command.spawn().map_err(|e| format!("amemo serve: {e}"))?;
        crate::log!("служба запущена: процесс {}", child.id());
        *self.child.lock().unwrap_or_else(|e| e.into_inner()) = Some(child);
        let deadline = Instant::now() + Duration::from_secs(120);
        while Instant::now() < deadline {
            if health(port) {
                return Ok(());
            }
            if let Some(code) = self.exited() {
                return Err(format!(
                    "служба amemo завершилась при запуске (код {code}):\n{}\nЖурнал — {}",
                    tail(&log_path, 6),
                    log_path.display()
                ));
            }
            thread::sleep(Duration::from_millis(500));
        }
        Err(format!("служба amemo не ответила за 2 минуты; журнал — {}", log_path.display()))
    }

    /// Код выхода службы, если она завершилась (и её больше нет в списке).
    fn exited(&self) -> Option<i32> {
        let mut child = self.child.lock().unwrap_or_else(|e| e.into_inner());
        let status = child.as_mut()?.try_wait().ok()??;
        *child = None;
        Some(status.code().unwrap_or(-1))
    }

    /// Слежение за службой — один поток на всё время работы приложения.
    fn watch(self: &Arc<Self>) {
        if self.watching.swap(true, Ordering::SeqCst) {
            return;
        }
        let me = self.clone();
        thread::spawn(move || loop {
            thread::sleep(Duration::from_secs(2));
            let Ok(_busy) = me.busy.try_lock() else { continue };
            if me.status() != Status::Ready {
                continue;
            }
            let Some(code) = me.exited() else { continue };
            crate::log!("служба завершилась сама (код {code})");
            let recent = {
                let mut restarts = me.restarts.lock().unwrap_or_else(|e| e.into_inner());
                restarts.retain(|t| t.elapsed() < Duration::from_secs(600));
                restarts.push(Instant::now());
                restarts.len()
            };
            if recent > 3 {
                me.set(Status::Failed(format!(
                    "служба amemo завершается снова и снова (код {code}); журнал — {}",
                    me.paths.logs().join("serve.log").display()
                )));
                continue;
            }
            me.set(Status::Starting);
            match me.bring_up() {
                Ok(()) => me.set(Status::Ready),
                Err(e) => me.set(Status::Failed(e)),
            }
        });
    }

    /// Остановить службу и кластер (пауза или выход). Ждёт окончания.
    pub fn stop(&self, pause: bool) {
        let _busy = self.busy.lock().unwrap_or_else(|e| e.into_inner());
        let had = self.status() != Status::Stopped && self.status() != Status::Paused;
        if let Some(mut child) = self.child.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = child.kill();
            let _ = child.wait();
            crate::log!("служба остановлена");
        }
        if had {
            if let Some(runtime) = self.paths.current() {
                if let Err(e) = pg(&runtime, "stop") {
                    crate::log!("{e}");
                }
            }
        }
        self.set(if pause { Status::Paused } else { Status::Stopped });
    }
}

/// `amemo pg start|stop` из комплекта.
fn pg(runtime: &std::path::Path, action: &str) -> Result<(), String> {
    let output = setup::amemo(runtime)
        .args(["pg", action])
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("amemo pg {action}: {e}"))?;
    if output.status.success() {
        return Ok(());
    }
    let text = String::from_utf8_lossy(&output.stderr);
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    Err(format!(
        "PostgreSQL amemo не {}: {}",
        if action == "start" { "запустился" } else { "остановился" },
        lines[lines.len().saturating_sub(4)..].join("\n")
    ))
}

/// `/health` службы отвечает 200 (HTTP/1.0 без библиотек: проверка раз в полсекунды).
pub fn health(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_secs(1)) else { return false };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    if stream.write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut head = [0u8; 16];
    let mut got = 0;
    while got < head.len() {
        match stream.read(&mut head[got..]) {
            Ok(0) | Err(_) => break,
            Ok(n) => got += n,
        }
    }
    let line = String::from_utf8_lossy(&head[..got]);
    line.starts_with("HTTP/1.") && line.get(9..12) == Some("200")
}

fn tail(path: &std::path::Path, lines: usize) -> String {
    let text = fs::read(path).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default();
    let all: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    all[all.len().saturating_sub(lines)..].join("\n")
}
