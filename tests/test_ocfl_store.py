"""Хранилище копий OCFL без базы: корень и объекты проходят валидатор ocfl-py, версии не теряют старое содержимое,
сбой записи в любом месте не оставляет корень испорченным."""
import hashlib
import json
import os
import shutil
import threading
import unicodedata

import pytest

from amemo import ocfl_store
from amemo.ids import uuid7
from amemo.ocfl_store import ObjectStore, StoreError, layout_path, ocfl_id
from ocfl_check import VALIDATOR, object_path, validate

USER = "model:claude"


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(tmp_path):
    s = ObjectStore(tmp_path / "objects")
    s.init(create=True)
    return s


def write(tmp_path, name: str, data: bytes):
    path = tmp_path / "docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def add(store, tmp_path, object_id, n, data: bytes, name="СП 20.13330.2016.pdf"):
    store.add_version(object_id, n, write(tmp_path, name, data), name, digest_of(data), user=USER, message="тест")


def assert_valid(store):
    if not VALIDATOR:              # Windows: валидатора нет (ocfl_check.NO_VALIDATOR) — проверки самого amemo идут дальше
        return
    ok, log = validate(store.root)
    assert ok, log


# корень

def test_new_root_is_valid_and_init_is_idempotent(store):
    store.init(create=False)
    assert_valid(store)
    layout = json.loads((store.root / "ocfl_layout.json").read_text())
    assert layout["extension"] == "0004-hashed-n-tuple-storage-layout"


def test_missing_root_is_created_only_on_request(tmp_path):
    """Пустая папка на месте хранилища, файлы которого база знает, — неподключённый том: молча новый корень не нужен."""
    with pytest.raises(StoreError, match="корня хранилища нет"):
        ObjectStore(tmp_path / "objects").init(create=False)
    assert not (tmp_path / "objects").exists()


def test_init_refuses_foreign_folder(tmp_path):
    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "чужой.txt").write_text("x")
    (tmp_path / "objects" / "выгрузка.tmp").write_text("x")
    with pytest.raises(StoreError, match="не корень OCFL"):
        ObjectStore(tmp_path / "objects").init(create=True)
    assert (tmp_path / "objects" / "выгрузка.tmp").exists()             # чужое не трогается


def test_init_finishes_half_created_root(tmp_path):
    """Сбой посреди создания корня: раскладка уже записана, объявления корня нет, остались временные файлы —
    init достраивает."""
    store = ObjectStore(tmp_path / "objects")
    store.init(create=True)
    (store.root / "0=ocfl_1.1").unlink()
    (store.root / "0=ocfl_1.1.tmp").write_text("ocfl_1")
    (store.root / "ocfl_layout.json.tmp").write_text("{")
    store.init(create=True)
    assert_valid(store)


def test_init_refuses_root_with_other_layout(store):
    (store.root / "ocfl_layout.json").write_text(json.dumps({"extension": "0002-flat-direct-storage-layout"}))
    with pytest.raises(StoreError, match="другая раскладка"):
        store.init(create=False)


def test_layout_matches_extension_examples():
    """Примеры из описания расширения 0004 (sha256, 3 × 3) — независимая сверка раскладки."""
    assert layout_path("object-01") == \
        "3c0/ff4/240/3c0ff4240c1e116dba14c7627f2319b58aa3d77606d0d90dfc6161608ac987d4"
    assert layout_path("..hor/rib:le-$id") == \
        "487/326/d8c/487326d8c2a3c0b885e23da1469b4d6671fd4e76978924b4443e9e3c316cda6d"


# версии

def test_versions_keep_old_content(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"%PDF edition 1")
    add(store, tmp_path, oid, 2, b"%PDF edition 2")
    assert store.head(oid) == 2
    assert store.content(oid, 1).read_bytes() == b"%PDF edition 1"
    assert store.content(oid, 2).read_bytes() == b"%PDF edition 2"
    assert_valid(store)


def test_object_lies_where_the_layout_says(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"x")
    assert store.object_dir(oid) == object_path(store.root, ocfl_id(oid))
    assert store.head(str(oid).upper()) == 1                           # id текстом в любом регистре — тот же


def test_same_content_in_new_version_is_not_copied(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    add(store, tmp_path, oid, 2, b"B")
    add(store, tmp_path, oid, 3, b"A")                           # файл вернули к первой редакции
    assert not (store.object_dir(oid) / "v3" / "content").exists()
    assert store.content(oid, 3) == store.content(oid, 1)
    assert_valid(store)


def test_large_file_is_copied_in_full(store, tmp_path):
    oid = uuid7()
    data = os.urandom(3 * ocfl_store.CHUNK + 17)
    add(store, tmp_path, oid, 1, data)
    assert store.content(oid, 1).read_bytes() == data
    assert_valid(store)


def test_names_are_nfc_and_long_ones_shortened_on_disk(store, tmp_path):
    oid, long_id = uuid7(), uuid7()
    nfd = unicodedata.normalize("NFD", "Таблица й.md")
    add(store, tmp_path, oid, 1, b"# x", name=nfd)
    assert store.content(oid, 1).name == unicodedata.normalize("NFC", nfd)
    long_name = "Протокол испытаний " * 9 + ".pdf"                    # ≈ 300 байт: NTFS пускает, ext4 — нет
    store.add_version(long_id, 1, write(tmp_path, "long.pdf", b"%PDF"), long_name, digest_of(b"%PDF"),
                      user=USER, message="тест")
    copy = store.content(long_id, 1)
    assert len(copy.name.encode("utf-8")) <= 255 and copy.suffix == ".pdf"
    inventory = json.loads((store.object_dir(long_id) / "inventory.json").read_text())
    assert inventory["versions"]["v1"]["state"] == {digest_of(b"%PDF")[7:]: [long_name]}   # логическое имя — целиком
    assert_valid(store)


@pytest.mark.parametrize("change", [lambda s, oid, tmp: None,
                                    lambda s, oid, tmp: add(s, tmp, oid, 1, b"A")], ids=["новый объект", "v2"])
def test_file_changed_while_copying_is_refused(store, tmp_path, change):
    oid = uuid7()
    change(store, oid, tmp_path)
    n = store.head(oid) + 1
    src = write(tmp_path, "a.pdf", b"new")
    with pytest.raises(StoreError, match="изменился"):
        store.add_version(oid, n, src, "a.pdf", digest_of(b"old"), user=USER, message="тест")
    assert store.head(oid) == n - 1
    assert_valid(store)


@pytest.mark.parametrize("n, message", [(3, "следующая версия — 2"), (0, "целое от 1")], ids=["через одну", "ноль"])
def test_wrong_version_number_is_refused(store, tmp_path, n, message):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    with pytest.raises(StoreError, match=message):
        add(store, tmp_path, oid, n, b"B")


def test_versions_newer_than_requested_are_refused(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    add(store, tmp_path, oid, 2, b"B")
    with pytest.raises(StoreError, match="новее 1"):
        add(store, tmp_path, oid, 1, b"C")
    assert store.head(oid) == 2


def test_bad_names_and_digests_and_missing_versions(store, tmp_path):
    oid = uuid7()
    with pytest.raises(StoreError, match="недопустимое имя"):
        store.add_version(oid, 1, write(tmp_path, "a", b"A"), "../a", digest_of(b"A"), user=USER, message="тест")
    with pytest.raises(StoreError, match="64 знака"):
        store.add_version(oid, 1, write(tmp_path, "a", b"A"), "a", digest_of(b"A").upper(), user=USER,
                          message="тест")
    with pytest.raises(StoreError, match="нет версии 1"):
        store.content(oid, 1)


# сбои

def test_version_written_but_not_recorded_is_accepted_again(store, tmp_path):
    """База не записала версию после записи в хранилище (сбой фиксации): та же запись проходит как есть."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    add(store, tmp_path, oid, 1, b"A")
    assert store.head(oid) == 1


@pytest.mark.parametrize("n", [1, 2])
def test_unrecorded_version_with_other_content_is_rolled_back(store, tmp_path, n):
    """База не знает версию n, а пришло другое содержимое: n откатывается и пишется заново."""
    oid = uuid7()
    for k in range(1, n + 1):
        add(store, tmp_path, oid, k, f"v{k}".encode())
    add(store, tmp_path, oid, n, b"other")
    assert store.head(oid) == n and store.content(oid, n).read_bytes() == b"other"
    if n == 2:
        assert store.content(oid, 1).read_bytes() == b"v1"
    assert_valid(store)


def _fail_on_replace(monkeypatch, target_name: str, nth: int = 1):
    """os.replace в хранилище падает на nth-й записи файла или папки с именем target_name."""
    real, seen = os.replace, {"n": 0}

    def replace(src, dst):
        if os.path.basename(dst) == target_name:
            seen["n"] += 1
            if seen["n"] == nth:
                raise OSError(28, "No space left on device")
        return real(src, dst)

    monkeypatch.setattr(ocfl_store.os, "replace", replace)


@pytest.mark.parametrize("target, nth", [("v2", 1), ("inventory.json", 2), ("inventory.json.sha256", 2)],
                         ids=["перенос v2", "корневой inventory", "корневой sidecar"])
def test_failure_while_adding_version_keeps_object_valid(store, tmp_path, monkeypatch, target, nth):
    """Ошибка файловой системы на любом шаге записи v2: StoreError; объект — прежний или с v2 целиком, корень цел."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    _fail_on_replace(monkeypatch, target, nth)
    with pytest.raises(StoreError, match="копия не записана"):
        add(store, tmp_path, oid, 2, b"B")
    monkeypatch.undo()
    assert_valid(store)
    assert store.head(oid) in (1, 2)
    add(store, tmp_path, oid, 2, b"B")                       # повтор той же записи (база её так и не записала)
    assert store.content(oid, 2).read_bytes() == b"B"
    assert_valid(store)


def test_failure_while_placing_new_object_leaves_no_folders(store, tmp_path, monkeypatch):
    oid = uuid7()
    _fail_on_replace(monkeypatch, layout_path(ocfl_id(oid)).rsplit("/", 1)[1])
    with pytest.raises(StoreError, match="копия не записана"):
        add(store, tmp_path, oid, 1, b"A")
    monkeypatch.undo()
    assert not store.object_dir(oid).parent.exists()
    assert_valid(store)


def _leave_mark(store, oid, name="tmpcrash"):
    """След жёсткого сбоя посреди записи: временная папка с отметкой, какой объект писался."""
    work = store.deposit / name
    work.mkdir(parents=True)
    (work / ocfl_store.MARK).write_text(str(oid))


def test_crash_leftovers_are_repaired_by_init(store, tmp_path):
    """После жёсткого сбоя: лишняя vN, устаревший sidecar, пустые папки нового объекта — init всё убирает."""
    stale, fresh = uuid7(), uuid7()
    add(store, tmp_path, stale, 1, b"A")
    obj = store.object_dir(stale)
    shutil.copytree(obj / "v1", obj / "v2")                          # vN без корневого inventory
    (obj / "inventory.json.sha256").write_text("0" * 64 + " inventory.json\n")    # sidecar от прошлой версии
    store.object_dir(fresh).parent.mkdir(parents=True)               # раскладка нового объекта, который не встал
    _leave_mark(store, stale, "a")
    _leave_mark(store, fresh, "b")
    assert not validate(store.root)[0]
    store.init(create=False)
    assert_valid(store)
    assert not (obj / "v2").exists() and not store.object_dir(fresh).parent.exists()
    assert list(store.deposit.iterdir()) == []


def test_crash_leftovers_are_repaired_by_next_write(store, tmp_path):
    oid, other = uuid7(), uuid7()
    add(store, tmp_path, oid, 1, b"A")
    shutil.copytree(store.object_dir(oid) / "v1", store.object_dir(oid) / "v2")
    _leave_mark(store, oid)
    add(store, tmp_path, other, 1, b"B")                             # любая следующая запись
    assert_valid(store)


def test_object_without_root_inventory_is_restored_not_deleted(store, tmp_path):
    """Корневой inventory пропал (объект трогали вручную, восстанавливали из бэкапа): записанные версии не теряются —
    inventory берётся у старшей целой версии, следующая запись идёт как обычно."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    add(store, tmp_path, oid, 2, b"B")
    (store.object_dir(oid) / "inventory.json").rename(tmp_path / "отложен.json")
    add(store, tmp_path, oid, 3, b"C")
    assert [store.content(oid, k).read_bytes() for k in (1, 2, 3)] == [b"A", b"B", b"C"]
    assert_valid(store)


def test_object_whose_newest_version_is_broken_is_kept_for_manual_repair(store, tmp_path):
    """Корневого inventory нет, а у старшей версии не сходится sidecar (восстановление из бэкапа прервалось):
    взять inventory младшей — значит удалить старшую, которую база, может быть, записала. Поэтому — ошибка."""
    oid = uuid7()
    for k, data in enumerate([b"A", b"B", b"C"], start=1):
        add(store, tmp_path, oid, k, data)
    obj = store.object_dir(oid)
    (obj / "inventory.json").unlink()
    (obj / "v3" / "inventory.json.sha256").unlink()
    with pytest.raises(StoreError, match="разбор вручную"):
        add(store, tmp_path, oid, 4, b"D")
    assert (obj / "v3" / "content").is_dir() and not (obj / "v4").exists()


def test_object_without_any_whole_version_is_kept_for_manual_repair(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    obj = store.object_dir(oid)
    (obj / "inventory.json").unlink()
    (obj / "v1" / "inventory.json.sha256").write_text("0" * 64 + " inventory.json\n")
    _leave_mark(store, oid)
    with pytest.raises(StoreError, match="разбор вручную"):
        store.init(create=False)
    assert (obj / "v1" / "content").is_dir()                           # ничего не удалено


def test_leftover_version_without_mark_does_not_fail_the_write(store, tmp_path):
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    shutil.copytree(store.object_dir(oid) / "v1", store.object_dir(oid) / "v2")     # след сбоя без отметки
    add(store, tmp_path, oid, 2, b"B")
    assert store.content(oid, 2).read_bytes() == b"B"
    assert_valid(store)


def test_hand_edited_inventory_is_not_resealed(store, tmp_path):
    """Починка пересчитывает sidecar только для inventory, который записало хранилище: правку вручную видно."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    path = store.object_dir(oid) / "inventory.json"
    sidecar = (store.object_dir(oid) / "inventory.json.sha256").read_bytes()
    inventory = json.loads(path.read_text())
    inventory["versions"]["v1"]["message"] = "правка вручную"
    path.write_text(json.dumps(inventory))
    src = write(tmp_path, "b.pdf", b"B")
    with pytest.raises(StoreError, match="изменился"):
        store.add_version(oid, 2, src, "b.pdf", digest_of(b"other"), user=USER, message="тест")
    assert (store.object_dir(oid) / "inventory.json.sha256").read_bytes() == sidecar
    assert not validate(store.root)[0]


def test_init_waits_for_write_in_progress(store, tmp_path, monkeypatch):
    """init() из другого процесса без блокировки базы не разбирает чужую запись на ходу: ждёт блокировку файла."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    moved, go = threading.Event(), threading.Event()
    real = ocfl_store._fsync_dir

    def pause_after_move(path):
        real(path)
        if path == store.object_dir(oid) and threading.current_thread().name == "writer":
            moved.set()                                               # v2 уже в объекте, корневой inventory — ещё нет
            go.wait(10)

    monkeypatch.setattr(ocfl_store, "_fsync_dir", pause_after_move)
    writer = threading.Thread(target=add, args=(store, tmp_path, oid, 2, b"B"), name="writer")
    other = threading.Thread(target=ObjectStore(store.root).init, kwargs={"create": False})
    writer.start()
    assert moved.wait(10)
    other.start()
    other.join(0.5)
    assert other.is_alive()                                           # ждёт, а не чинит
    go.set()
    writer.join(10)
    other.join(10)
    assert store.content(oid, 2).read_bytes() == b"B"
    assert_valid(store)


def test_validator_catches_damaged_copy(store, tmp_path):
    """Проверка самой проверки: испорченная копия файла видна валидатору."""
    oid = uuid7()
    add(store, tmp_path, oid, 1, b"A")
    store.content(oid, 1).write_bytes(b"B")
    assert not validate(store.root)[0]
