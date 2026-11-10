"""amemo embed enable|status и строка «смысловой поиск» у amemo doctor: на настоящей базе (PostgreSQL 18).

Пакет fastembed подменён (сети и модели нет): файлы модели «появляются» в папке только после скачивания с
разрешения (local_files_only=False), и до него провайдер из локальных файлов не создаётся — как у fastembed.
"""
import importlib.machinery
import json
import os
import sys
import types
from pathlib import Path

import pytest

from amemo import cli, db, embed, records
from amemo.cli.commands import embed as embed_cmd
from amemo.records import Item
from conftest import FakeProvider

AGENT = "model:test"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def models(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "models"
    monkeypatch.setenv("AMEMO_MODELS", str(folder))
    return folder


@pytest.fixture
def fastembed(monkeypatch, models):
    """Подменный пакет fastembed: created — аргументы каждого TextEmbedding, cached — папки со «скачанной» моделью,
    embedded — тексты, по которым считались вектора."""
    state = types.SimpleNamespace(created=[], cached=set(), embedded=[])

    class TextEmbedding:
        def __init__(self, *, model_name, cache_dir, lazy_load, local_files_only):
            state.created.append({"model_name": model_name, "cache_dir": cache_dir,
                                  "local_files_only": local_files_only})
            if local_files_only and cache_dir not in state.cached:
                raise ValueError("Could not find model files in the local cache")
            state.cached.add(cache_dir)

        def embed(self, texts):
            for text in texts:
                state.embedded.append(text)
                yield FakeProvider.vector(text)

    module = types.ModuleType("fastembed")
    module.__spec__ = importlib.machinery.ModuleSpec("fastembed", None)
    module.TextEmbedding = TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", module)
    state.downloads = lambda: [c for c in state.created if not c["local_files_only"]]
    return state


@pytest.fixture
def run(dsn, kb, tmp_path, capsys, monkeypatch):
    """run(*argv, extra=…) → (код, stdout, stderr): обычный терминал человека ann; stdin — не терминал."""
    monkeypatch.chdir(tmp_path)                      # не корень git: doctor не ищет агентов проекта
    monkeypatch.setattr(sys, "stdin", Stdin(""))
    env = {"AMEMO_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann", "AMEMO_DATA": str(tmp_path / "objects"),
           "AMEMO_STATE": str(tmp_path / "state"), "PATH": os.environ.get("PATH", "")}

    def call(*argv, extra=None):
        code = cli.main(list(argv), env={**env, **(extra or {})})
        out, err = capsys.readouterr()
        return code, out, err
    return call


class Stdin:
    """stdin для вопроса: tty — интерактивный ли терминал, answer — что «ввёл» человек."""

    def __init__(self, answer: str, tty: bool = False):
        self.answer, self.tty, self.read = answer, tty, 0

    def isatty(self):
        return self.tty

    def readline(self):
        self.read += 1
        return self.answer


def put_atom(kb, label: str, key: str):
    return records.commit(kb, [Item("atom", {
        "ref": "@fact", "kind": "fact", "key": key,
        "label": {"ru": label}, "summary_plain": {"ru": f"Пояснение: {label}"},
    })], agent=AGENT).revisions[0]


def js(out: str):
    return json.loads(out)


def models_in(kb) -> list[tuple]:
    return kb.execute("SELECT name, backend, active FROM embedding_model ORDER BY created_at").fetchall()


def semantic_line(run) -> dict:
    code, out, _ = run("doctor", "--json")
    return next(c for c in js(out)["checks"] if c["name"] == "смысловой поиск")


# --- папка модели ---

def test_models_dir_is_persistent_by_default_and_follows_the_environment(monkeypatch, tmp_path):
    assert embed.models_dir({"HOME": "/h"}) == Path("/h/.local/share/amemo/models")
    assert embed.models_dir({"HOME": "/h", "FASTEMBED_CACHE_PATH": "/cache"}) == Path("/cache")
    assert embed.models_dir({"HOME": "/h", "FASTEMBED_CACHE_PATH": "/cache", "AMEMO_MODELS": "~/m"}) == \
        Path("~/m").expanduser()
    monkeypatch.setenv("AMEMO_MODELS", str(tmp_path / "m"))
    assert embed.FastembedProvider().cache_dir == str(tmp_path / "m")      # служба, mcp и проверка ищут там же
    assert embed.FastembedProvider(cache_dir="/explicit").cache_dir == "/explicit"


# --- enable ---

def test_enable_with_yes_downloads_embeds_every_document_and_activates(run, kb, fastembed, models):
    put_atom(kb, "Альфа", "alpha")
    put_atom(kb, "Бета", "beta")
    code, out, err = run("embed", "enable", "--yes", "--json")
    assert code == 0, err
    result = js(out)
    assert result["downloaded"] is True and result["models_dir"] == str(models)
    assert result["model"]["name"] == embed.DEFAULT_MODEL and result["model"]["backend"] == "fastembed"
    assert result["model"]["active"] is True and result["model"]["dims"] == 384
    coverage = result["coverage"]
    assert coverage["complete"] and coverage["total"] >= 2 and result["embedded"] == coverage["total"]
    assert "скачиваю модель" in err and "считаю вектора" in err
    assert [c["local_files_only"] for c in fastembed.created] == [True, False]   # сначала кэш, потом сеть
    assert {c["cache_dir"] for c in fastembed.created} == {str(models)}
    assert models_in(kb) == [(embed.DEFAULT_MODEL, "fastembed", True)]

    code, out, _ = run("embed", "status", "--json")
    status = js(out)
    assert code == 0 and status["semantic"] == "used" and status["reason"] is None
    assert status["coverage"]["complete"] and status["model"]["id"] == result["model"]["id"]
    assert embed_cmd.next_step(status) is None
    line = semantic_line(run)
    assert line["status"] == "ok" and embed.DEFAULT_MODEL in line["detail"]


def test_enable_without_permission_downloads_and_registers_nothing(run, kb, fastembed):
    put_atom(kb, "Альфа", "alpha")
    code, _, err = run("embed", "enable")
    assert code == 2 and "только с разрешения" in err and "amemo embed enable --yes" in err
    code, out, _ = run("embed", "enable", "--json")
    assert code == 2 and js(out)["code"] == "download_not_allowed"
    assert fastembed.downloads() == [] and models_in(kb) == []


def test_enable_asks_a_person_in_a_terminal(run, kb, fastembed, monkeypatch):
    put_atom(kb, "Альфа", "alpha")
    asked = Stdin("y\n", tty=True)
    monkeypatch.setattr(sys, "stdin", asked)
    code, out, _ = run("embed", "enable", "--json")                             # --json не спрашивает
    assert code == 2 and js(out)["code"] == "download_not_allowed" and asked.read == 0
    code, _, _ = run("embed", "enable", extra={"CI": "true"})                   # и CI не спрашивает
    assert code == 2 and asked.read == 0

    monkeypatch.setattr(sys, "stdin", Stdin("\n", tty=True))
    code, _, err = run("embed", "enable")
    assert code == 2 and "Скачать модель смыслового поиска" in err and "не включён" in err
    assert fastembed.downloads() == [] and models_in(kb) == []

    monkeypatch.setattr(sys, "stdin", Stdin("да\n", tty=True))
    code, out, err = run("embed", "enable")
    assert code == 0, err
    assert "скачана в" in out and "смысловой поиск включён" in out
    assert len(fastembed.downloads()) == 1 and models_in(kb)[0][2] is True


def test_rerun_uses_local_files_and_catches_up_new_records(run, kb, fastembed):
    put_atom(kb, "Альфа", "alpha")
    assert run("embed", "enable", "--yes")[0] == 0
    put_atom(kb, "Гамма", "gamma")                       # запись сама вектор не считает
    code, out, _ = run("embed", "status", "--json")
    status = js(out)
    assert status["semantic"] == "used" and status["coverage"]["missing"] == 1
    assert "amemo embed enable" in embed_cmd.next_step(status)
    line = semantic_line(run)
    assert line["status"] == "warn" and "amemo embed enable" in line["detail"]

    downloads = len(fastembed.downloads())
    code, out, err = run("embed", "enable", "--json")    # без --yes: модель уже в папке, вопроса нет
    assert code == 0, err
    result = js(out)
    assert result["downloaded"] is False and result["embedded"] == 1 and result["coverage"]["complete"]
    assert len(fastembed.downloads()) == downloads
    assert len(models_in(kb)) == 1


def test_enable_counts_again_when_a_record_lands_before_activation(run, kb, fastembed, monkeypatch):
    put_atom(kb, "Альфа", "alpha")
    activate = embed.activate_model
    calls = []

    def racing(conn, model_id):
        calls.append(model_id)
        if len(calls) == 1:
            put_atom(kb, "Дельта", "delta")              # другая запись успела между счётом и активацией
        return activate(conn, model_id)

    monkeypatch.setattr(embed, "activate_model", racing)
    code, out, err = run("embed", "enable", "--yes", "--json")
    assert code == 0, err
    assert len(calls) == 2 and js(out)["coverage"]["complete"]


@pytest.mark.parametrize("extra", [{"CLAUDECODE": "1"}, {"AMEMO_AS_MODEL": "bot"}])
def test_enable_is_for_a_person_only(run, kb, fastembed, extra):
    code, _, err = run("embed", "enable", "--yes", extra=extra)
    assert code == 2 and "только человек" in err
    assert fastembed.created == [] and models_in(kb) == []
    assert run("embed", "status", extra=extra)[0] == 0                         # смотреть можно


def test_enable_refuses_a_disabled_backend_and_a_missing_package(run, kb, fastembed, monkeypatch):
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    code, out, _ = run("embed", "enable", "--yes", "--json")
    assert code == 2 and js(out)["code"] == "backend_disabled"
    monkeypatch.setenv("AMEMO_BACKEND", "other")
    code, out, _ = run("embed", "enable", "--yes", "--json")
    assert code == 2 and js(out)["code"] == "backend_unknown"
    monkeypatch.delenv("AMEMO_BACKEND")
    monkeypatch.setitem(sys.modules, "fastembed", None)
    code, _, err = run("embed", "enable", "--yes")
    assert code == 1 and "uv tool install 'amemo[web,embed]'" in err
    assert fastembed.created == [] and models_in(kb) == []


def test_enable_reports_a_failed_download(run, kb, fastembed, monkeypatch):
    class Offline:
        def __init__(self, **kwargs):
            raise OSError("network is unreachable")

    monkeypatch.setattr(sys.modules["fastembed"], "TextEmbedding", Offline)
    code, out, _ = run("embed", "enable", "--yes", "--json")
    assert code == 1 and js(out)["code"] == "embed_download" and "network is unreachable" in js(out)["detail"]
    assert models_in(kb) == []


# --- status и doctor ---

def test_status_without_a_model_points_to_enable(run, kb, fastembed):
    put_atom(kb, "Альфа", "alpha")
    code, out, _ = run("embed", "status")
    assert code == 0
    assert "недоступен (no_active_model)" in out and "активной модели нет" in out
    assert "дальше: включить: amemo embed enable" in out
    code, out, _ = run("embed", "status", "--json")
    status = js(out)
    assert status["model"] is None and status["coverage"] is None and status["documents"] >= 1
    assert status["fastembed"] is True and status["backend"] == "fastembed"
    line = semantic_line(run)
    assert line["status"] == "warn" and "amemo embed enable" in line["detail"]
    assert fastembed.downloads() == []                                          # status ничего не качает


def test_doctor_without_the_package_names_the_extra_and_the_command(run, kb, monkeypatch, models):
    monkeypatch.setitem(sys.modules, "fastembed", None)
    line = semantic_line(run)
    assert line["status"] == "warn"
    assert "uv tool install 'amemo[web,embed]'" in line["detail"] and "amemo embed enable" in line["detail"]


def test_doctor_with_backend_none_says_how_to_turn_it_on(run, kb, monkeypatch):
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    line = semantic_line(run)
    assert line["status"] == "warn" and "AMEMO_BACKEND=none" in line["detail"]


def test_status_notices_model_files_gone_from_the_folder(run, kb, fastembed):
    put_atom(kb, "Альфа", "alpha")
    assert run("embed", "enable", "--yes")[0] == 0
    fastembed.cached.clear()                             # папку модели вычистили
    code, out, _ = run("embed", "status", "--json")
    status = js(out)
    assert code == 0 and status["semantic"] == "unavailable" and status["reason"] == "embedding_failed"
    assert "скачать заново" in embed_cmd.next_step(status)
    assert semantic_line(run)["status"] == "warn"
    code, out, err = run("embed", "enable", "--yes", "--json")                  # enable качает снова
    assert code == 0, err
    assert js(out)["downloaded"] is True


def test_embed_group_without_action_shows_help(run):
    assert run("embed")[0] == 2
    assert run("embed", "--help")[0] == 0
