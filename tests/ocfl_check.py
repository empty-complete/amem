"""Проверка корня OCFL валидатором ocfl-py. Раскладки 0004 в ocfl-py 2.1 нет — она регистрируется здесь,
по описанию расширения (https://ocfl.github.io/extensions/0004-hashed-n-tuple-storage-layout.html)."""
from pathlib import Path

import ocfl
from ocfl import layout_registry
from ocfl.digest import string_digest
from ocfl.layout_0003_hash_and_id_n_tuple import Layout_0003_Hash_And_Id_N_Tuple


class Layout0004(Layout_0003_Hash_And_Id_N_Tuple):
    """Как 0003, но папка объекта — весь хэш id (или его хвост при shortObjectRoot), без самого id."""

    def __init__(self):
        super().__init__()
        self.NAME = "0004-hashed-n-tuple-storage-layout"
        self.DESCRIPTION = "Extension 0004: Hashed N-tuple Storage Layout"
        self.short_object_root = False
        self.PARAMS["shortObjectRoot"] = self.check_short_object_root

    def check_short_object_root(self, value):
        self.short_object_root = bool(value)

    @property
    def config(self):
        return {**super().config, "shortObjectRoot": self.short_object_root}

    def identifier_to_path(self, identifier):
        digest = string_digest(identifier, self.digest_algorithm).lower()
        parts = [digest[i * self.tuple_size:(i + 1) * self.tuple_size] for i in range(self.number_of_tuples)]
        tail = digest[self.tuple_size * self.number_of_tuples:] if self.short_object_root else digest
        return "/".join([*parts, tail])        # путь pyfilesystem: всегда «/», и на Windows


layout_registry.add_layout(Layout0004().NAME, Layout0004)


def validate(root: Path) -> tuple[bool, str]:
    """Корень и все объекты валидны. validate() ocfl-py считает только ошибки обхода корня: испорченный объект
    видно лишь по good_objects < num_objects — поэтому сверяются и они; в сообщении — ошибки объектов и обхода."""
    store = ocfl.StorageRoot(root=str(root))
    ok = store.validate(log_warnings=False)
    report = f"{store.num_objects=} {store.good_objects=}\nобъекты: {store.errors}\nкорень: {store.log}"
    return ok and store.num_objects == store.good_objects, report


def object_path(root: Path, identifier: str) -> Path:
    """Папка объекта по раскладке корня — как её вычисляет ocfl-py, независимо от amemo.ocfl_store."""
    store = ocfl.StorageRoot(root=str(root))
    store.open_root_fs()
    store.check_root_structure()
    return Path(root) / store.object_path(identifier)
