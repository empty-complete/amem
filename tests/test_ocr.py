"""Распознавание сканов — расширение на выбор: настройки ocr, ocr_data, ocr_languages; sources.ocr_setup и явная
папка данных у PyMuPDF; amemo ocr install|list|remove (скачивание подменено, сети нет), amemo doctor. Без базы."""
import json
import os
import socket
import stat
import struct
import tomllib
from pathlib import Path

import pymupdf
import pytest

from amemo import cli, settings, sources
from amemo.cli.commands import ocr
from samples import SCAN_PAGES, SP_PAGES, make_scanned_pdf

ENTRIES = 24


def traineddata(size: int = 4096) -> bytes:
    """Заголовок контейнера tessdata, как у tessdata_fast: 24 части, первые 17 пусты (-1)."""
    table = 4 + 8 * ENTRIES
    offsets = [-1] * 17 + [table + 100 * i for i in range(ENTRIES - 17)]
    head = struct.pack("<i", ENTRIES) + b"".join(struct.pack("<q", o) for o in offsets)
    return head + b"\0" * (size - len(head))


@pytest.fixture
def fetched(monkeypatch):
    """Подмена ocr.fetch: список адресов, а что отдать — body (bytes или исключение) по адресу."""
    calls = []
    body = {}

    def fake(url, out):
        calls.append(url)
        got = body.get(url.rsplit("/", 1)[-1].removesuffix(".traineddata"), traineddata())
        if isinstance(got, Exception):
            raise got
        out.write(got)

    monkeypatch.setattr(ocr, "fetch", fake)
    fake.calls, fake.body = calls, body
    return fake


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def run(home, capsys, monkeypatch):
    """run(*argv, extra=…) → (код, stdout, stderr): обычный терминал человека ann, HOME во временной папке."""
    monkeypatch.chdir(home.parent)

    def call(*argv, extra=None):
        environ = {"HOME": str(home), "USER": "ann", "PATH": os.environ.get("PATH", "")}
        environ.update(extra or {})
        code = cli.main(list(argv), env=environ)
        out, err = capsys.readouterr()
        return code, out, err
    return call


def data_dir(home: Path) -> Path:
    return home / ".local" / "share" / "amemo" / "tessdata"


def config_of(home: Path) -> Path:
    return home / ".config" / "amemo" / "amemo.toml"


def no_system(monkeypatch):
    monkeypatch.setattr(sources, "system_tessdata", lambda: None)


# --- настройки ---

def test_settings_ocr_defaults(tmp_path):
    s = settings.load({"HOME": str(tmp_path), "USER": "ann"})
    assert s.ocr == "auto"
    assert s.ocr_data == tmp_path / ".local" / "share" / "amemo" / "tessdata"     # рядом с хранилищем копий
    assert s.ocr_languages == ("rus", "eng")


@pytest.mark.parametrize("value, languages", [
    ("rus+eng", ("rus", "eng")), ("deu, eng", ("deu", "eng")), ("chi_sim eng eng", ("chi_sim", "eng")),
])
def test_settings_ocr_from_environment(tmp_path, value, languages):
    s = settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_OCR": "None", "AMEMO_OCR_LANGUAGES": value,
                       "AMEMO_OCR_DATA": str(tmp_path / "td")})
    assert (s.ocr, s.ocr_languages, s.ocr_data) == ("none", languages, tmp_path / "td")


def test_settings_ocr_in_toml(tmp_path):
    config = tmp_path / "amemo.toml"
    config.write_text('ocr = "tesseract"\nocr_languages = ["rus", "deu"]\nocr_data = "td"\n', encoding="utf-8")
    s = settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_CONFIG": str(config)})
    assert (s.ocr, s.ocr_languages, s.ocr_data) == ("tesseract", ("rus", "deu"), tmp_path / "td")


@pytest.mark.parametrize("env, words", [
    ({"AMEMO_OCR": "cloud"}, "ещё не поддерживается"),          # облако зарезервировано
    ({"AMEMO_OCR": "abbyy"}, "AMEMO_OCR"),
    ({"AMEMO_OCR_LANGUAGES": "rus+Рус"}, "AMEMO_OCR_LANGUAGES"),
    ({"AMEMO_OCR_LANGUAGES": "en"}, "AMEMO_OCR_LANGUAGES"),     # коды tessdata — от трёх знаков
])
def test_settings_ocr_errors(tmp_path, env, words):
    with pytest.raises(settings.SettingsError, match=words):
        settings.load({"HOME": str(tmp_path), "USER": "ann", **env})


# --- где данные ---

def config(tmp_path, **env) -> settings.Settings:
    return settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_OCR_DATA": str(tmp_path / "td"), **env})


def test_ocr_setup_prefers_own_data_then_system(tmp_path, monkeypatch):
    system = tmp_path / "system"
    system.mkdir()
    (system / "eng.traineddata").write_bytes(b"")
    monkeypatch.setattr(pymupdf, "get_tessdata", lambda tessdata=None: str(system))
    got = sources.ocr_setup(config(tmp_path))
    assert got == sources.OcrSetup(system, "eng", system=True)       # TESSDATA_PREFIX и пакет ОС — как раньше
    (tmp_path / "td").mkdir()
    (tmp_path / "td" / "rus.traineddata").write_bytes(b"")
    assert sources.ocr_setup(config(tmp_path)) == sources.OcrSetup(tmp_path / "td", "rus")
    assert sources.ocr_languages(config(tmp_path)) == "rus"


def test_ocr_none_is_off_even_with_data(tmp_path, monkeypatch):
    (tmp_path / "td").mkdir()
    (tmp_path / "td" / "rus.traineddata").write_bytes(b"")
    assert sources.ocr_setup(config(tmp_path, AMEMO_OCR="none")) is None
    no_system(monkeypatch)
    (tmp_path / "td" / "rus.traineddata").unlink()
    assert sources.ocr_setup(config(tmp_path, AMEMO_OCR="tesseract")) is None      # нечем: OCR недоступен


def test_ocr_reads_settings_and_passes_tessdata_to_pymupdf(tmp_path, monkeypatch):
    """Путь к данным берётся из настроек и передаётся PyMuPDF явно (tessdata=), а не через окружение."""
    folder = tmp_path / "td"
    folder.mkdir()
    (folder / "rus.traineddata").write_bytes(b"")
    monkeypatch.setenv("AMEMO_OCR_DATA", str(folder))
    no_system(monkeypatch)
    seen = []

    def fake_ocr(page, **kw):
        seen.append(kw)
        return page.get_textpage()

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", fake_ocr)
    scan = make_scanned_pdf(tmp_path / "скан.pdf", SCAN_PAGES)
    sources.extract_text(scan)
    assert seen and all(kw["tessdata"] == str(folder) and kw["language"] == "rus" for kw in seen)
    seen.clear()
    monkeypatch.setenv("AMEMO_OCR", "none")
    got = sources.extract_text(scan)
    assert not seen and got.ocr_unavailable and got.pages is None              # «нечем распознать», как раньше


@pytest.mark.parametrize("bad", ["cloud", "abbyy"])
def test_bad_ocr_setting_does_not_break_extraction(tmp_path, monkeypatch, caplog, bad):
    """Неверная настройка не роняет извлечение: одно предупреждение, сканы — «нечем распознать» (image)."""
    monkeypatch.setenv("AMEMO_OCR", bad)
    monkeypatch.setattr(sources, "_WARNED", set())
    scan = make_scanned_pdf(tmp_path / "скан.pdf", SCAN_PAGES)
    with caplog.at_level("WARNING", logger="amemo.sources"):
        got = sources.extract_text(scan)
        again = sources.extract_text(scan)
    assert got.pages is None and got.ocr_unavailable and again.ocr_unavailable
    mixed = sources.extract_text(make_scanned_pdf(tmp_path / "смешанный.pdf", [SP_PAGES[0], SCAN_PAGES[1]],
                                                  text_pages=(0,)))
    assert mixed.image == {2} and mixed.ocr == frozenset()
    assert [r.getMessage() for r in caplog.records].count(caplog.records[0].getMessage()) == 1
    assert "AMEMO_OCR" in caplog.records[0].getMessage()
    with pytest.raises(settings.SettingsError):
        settings.load()                                         # служба и CLI при старте по-прежнему отказывают


def test_broken_config_does_not_break_extraction(tmp_path, monkeypatch):
    config = tmp_path / "amemo.toml"
    config.write_text("ocr = ", encoding="utf-8")
    monkeypatch.setenv("AMEMO_CONFIG", str(config))
    got = sources.extract_text(make_scanned_pdf(tmp_path / "скан.pdf", SCAN_PAGES))
    assert got.pages is None and got.ocr_unavailable


# --- amemo ocr ---

def test_install_downloads_atomically_and_turns_ocr_on(run, home, fetched):
    config_of(home).parent.mkdir(parents=True)
    config_of(home).write_text('# мой файл\ndsn = "postgresql://x/db"\nocr_languages = [\n  "deu",\n]\n',
                               encoding="utf-8")
    config_of(home).chmod(0o600)
    code, out, err = run("ocr", "install", "rus,eng", "--json")
    assert code == 0, err
    result = json.loads(out)
    assert [x["language"] for x in result["installed"]] == ["rus", "eng"] and result["quality"] == "fast"
    assert fetched.calls == ["https://github.com/tesseract-ocr/tessdata_fast/raw/main/rus.traineddata",
                             "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata"]
    assert sorted(p.name for p in data_dir(home).iterdir()) == ["eng.traineddata", "rus.traineddata"]  # без .tmp
    text = config_of(home).read_text(encoding="utf-8")
    assert text.startswith("# мой файл\n")                                      # чужое и комментарии — на месте
    assert tomllib.loads(text) == {"dsn": "postgresql://x/db", "ocr": "tesseract", "ocr_languages": ["rus", "eng"]}
    assert stat.S_IMODE(config_of(home).stat().st_mode) == 0o600
    s = settings.load({"HOME": str(home), "USER": "ann"})
    assert sources.ocr_setup(s) == sources.OcrSetup(data_dir(home), "rus+eng")

    code, out, _ = run("ocr", "install", "rus")                                 # повтор ничего не качает
    assert code == 0 and len(fetched.calls) == 2 and "уже установлен" in out
    code, _, _ = run("ocr", "install", "rus", "--force", "--quality", "best")
    assert code == 0 and fetched.calls[-1] == "https://github.com/tesseract-ocr/tessdata_best/raw/main/rus.traineddata"


def test_install_creates_config_0600_and_no_config_leaves_it(run, home, fetched):
    assert run("ocr", "install", "eng", "--no-config")[0] == 0
    assert not config_of(home).exists() and (data_dir(home) / "eng.traineddata").is_file()
    assert run("ocr", "install", "deu")[0] == 0
    assert tomllib.loads(config_of(home).read_text(encoding="utf-8")) == {"ocr": "tesseract",
                                                                          "ocr_languages": ["eng", "deu"]}
    assert stat.S_IMODE(config_of(home).stat().st_mode) == 0o600


@pytest.mark.parametrize("body, exit_code, words", [
    (ocr.DownloadError("ответ 404", 404), 4, "нет в tessdata_fast"),
    (ocr.DownloadError("сеть недоступна"), 1, "скачать не удалось"),
    (b"<!DOCTYPE html><html>rate limited</html>", 1, "не языковые данные"),
    (b"", 1, "не языковые данные"),
])
def test_install_refuses_bad_download(run, home, fetched, body, exit_code, words):
    (data_dir(home)).mkdir(parents=True)
    (data_dir(home) / "rus.traineddata").write_bytes(b"old")
    fetched.body["rus"] = body
    code, _, err = run("ocr", "install", "rus", "--force")
    assert code == exit_code and words in err
    assert sorted(p.name for p in data_dir(home).iterdir()) == ["rus.traineddata"]      # временного не осталось
    assert (data_dir(home) / "rus.traineddata").read_bytes() == b"old"                 # прежний файл цел
    assert not config_of(home).exists()


def test_install_checks_language_codes(run, home, fetched):
    for bad in ("Рус", "en", "../x", "eng.traineddata"):
        code, out, _ = run("ocr", "install", bad, "--json")
        assert code == 2 and json.loads(out)["code"] == "usage", bad
    assert fetched.calls == []


def test_model_cannot_change_installation(run, home, fetched):
    for extra in ({"CLAUDECODE": "1"}, {"AMEMO_AS_MODEL": "bot"}):
        code, _, err = run("ocr", "install", "rus", extra=extra)
        assert code == 2 and "только человек" in err
        code, _, _ = run("ocr", "remove", "rus", extra=extra)
        assert code == 2
    assert fetched.calls == [] and not data_dir(home).exists()
    assert run("ocr", "list", extra={"CLAUDECODE": "1"})[0] == 0                 # смотреть можно


def test_list_and_remove(run, home, fetched, monkeypatch):
    no_system(monkeypatch)
    code, out, _ = run("ocr", "list", "--json")
    assert code == 0 and json.loads(out) | {"data": None} == {
        "mode": "none", "setting": "auto", "languages": [], "tessdata": None, "system": False, "data": None,
        "installed": [], "wanted": ["rus", "eng"]}
    assert run("ocr", "install", "rus", "eng")[0] == 0
    code, out, _ = run("ocr", "list", "--json")
    listed = json.loads(out)
    assert (listed["mode"], listed["setting"], listed["languages"], listed["installed"]) == (
        "tesseract", "tesseract", ["rus", "eng"], ["eng", "rus"])
    assert listed["tessdata"] == listed["data"] == str(data_dir(home))
    code, _, err = run("ocr", "remove", "deu")
    assert code == 4 and "нет языков: deu" in err
    assert run("ocr", "remove", "eng")[0] == 0
    assert tomllib.loads(config_of(home).read_text(encoding="utf-8"))["ocr_languages"] == ["rus"]
    code, out, _ = run("ocr", "remove", "rus", "--json")
    assert code == 0 and json.loads(out)["left"] == []
    assert tomllib.loads(config_of(home).read_text(encoding="utf-8")) == {}      # языков нет — снова auto
    assert json.loads(run("ocr", "list", "--json")[1])["mode"] == "none"


def test_cloud_is_reserved(run):
    code, out, _ = run("ocr", "list", "--json", extra={"AMEMO_OCR": "cloud"})
    assert code == 2 and "ещё не поддерживается" in json.loads(out)["detail"]


def test_traineddata_header():
    assert ocr.looks_like_traineddata(traineddata(), 4096)
    assert not ocr.looks_like_traineddata(traineddata()[:100], 4096)
    assert not ocr.looks_like_traineddata(b"<html>" + b"\0" * 400, 4096)
    assert not ocr.looks_like_traineddata(struct.pack("<i", 2) + struct.pack("<q", -1) * 2, 20)   # частей нет


# --- doctor ---

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def doctor_ocr(run, **extra) -> dict:
    _, out, _ = run("doctor", "--json", extra={"AMEMO_PORT": str(_free_port()), **extra})
    return next(c for c in json.loads(out)["checks"] if c["name"] == "OCR")


def test_doctor_ocr_line(run, home, fetched, monkeypatch):
    no_system(monkeypatch)
    found = doctor_ocr(run)
    assert found["status"] == "ok" and "не установлено" in found["detail"]
    found = doctor_ocr(run, AMEMO_OCR="tesseract")
    assert found["status"] == "warn" and "amemo ocr install rus eng" in found["detail"]
    assert doctor_ocr(run, AMEMO_OCR="none")["status"] == "ok"
    assert run("ocr", "install", "rus")[0] == 0
    found = doctor_ocr(run)
    assert found["status"] == "ok" and "rus" in found["detail"] and str(data_dir(home)) in found["detail"]
