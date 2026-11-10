-- Схема v1, часть 2.2: объекты источников и источники ревизий. Совместимо с PostgreSQL 16.

-- Имена и пути сравниваются в NFC (normalize): это работает только в базе UTF8 — её проверяет db.migrate.

-- Объект — файл (копия по хэшу в хранилище OCFL data/objects), страница сайта или переписка.
-- У страницы сайта и переписки копии нет; их одна версия — без digest.
CREATE TABLE object (
    id             uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    kind           text NOT NULL CHECK (kind = ANY (ARRAY['file', 'web', 'message'])),
    original_name  text CHECK (original_name IS NULL OR (original_name <> ''
                                                         AND original_name = normalize(original_name, NFC))),
    media_type     text,
    format_puid    text,
    url            text CHECK (url IS NULL OR (url <> '' AND url = normalize(url, NFC))),
    retrieved_at   date,
    created_at     timestamptz NOT NULL,
    UNIQUE (id, kind),              -- версии и пути ссылаются на объект вместе с его видом
    CHECK ((kind = 'web') = (url IS NOT NULL)),
    CHECK ((kind = 'web') = (retrieved_at IS NOT NULL)),
    CHECK (kind = 'web' OR original_name IS NOT NULL)
);
-- страница сайта — одна на адрес, переписка — одна на название
CREATE UNIQUE INDEX object_web_url ON object (url) WHERE kind = 'web';
CREATE UNIQUE INDEX object_message_name ON object (original_name) WHERE kind = 'message';

-- Пути файла в папке документов (logical_paths): путь принадлежит одному объекту, объект лежит по нескольким путям.
-- Путь бывает только у файла: внешний ключ вместе с видом.
CREATE TABLE object_path (
    path       text PRIMARY KEY CHECK (path <> '' AND path = normalize(path, NFC)),
    object_id  uuid NOT NULL,
    kind       text NOT NULL DEFAULT 'file' CHECK (kind = 'file'),
    added_at   timestamptz NOT NULL,
    FOREIGN KEY (object_id, kind) REFERENCES object (id, kind)
);
CREATE INDEX object_path_object ON object_path (object_id);

-- Версия объекта — состояние файла. Одно содержимое — одна версия во всей базе (digest уникален).
-- Вид объекта повторён здесь под внешним ключом: копия и хэш — только у файла, у сайта и переписки одна версия.
CREATE TABLE object_version (
    object_id    uuid NOT NULL,
    kind         text NOT NULL,
    n            integer NOT NULL CHECK (n >= 1),
    digest       text UNIQUE CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
    size         bigint CHECK (size >= 0),
    recorded_at  timestamptz NOT NULL,
    PRIMARY KEY (object_id, n),
    FOREIGN KEY (object_id, kind) REFERENCES object (id, kind),
    CHECK ((digest IS NULL) = (size IS NULL)),
    CHECK ((kind = 'file') = (digest IS NOT NULL)),
    CHECK (kind = 'file' OR n = 1)
);

-- Текст версии файла по страницам — кэш по содержимому (digest), а не по пути; строки в NFC.
-- page 0 — у файла нет извлекаемого текста. Кэш можно очистить: он строится заново.
CREATE TABLE object_text (
    digest  text NOT NULL REFERENCES object_version (digest),
    page    integer NOT NULL CHECK (page >= 0),
    text    text NOT NULL,
    PRIMARY KEY (digest, page),
    CHECK (page > 0 OR text = '')
);

-- Что из объекта атомизировано: журнал отметок, текущая — последняя.
CREATE TABLE object_status (
    id          uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    object_id   uuid NOT NULL REFERENCES object (id),
    status      text NOT NULL CHECK (status = ANY (ARRAY['parsed', 'partial', 'skipped'])),
    note        text,
    agent       text NOT NULL REFERENCES agent (id),
    changed_at  timestamptz NOT NULL
);
CREATE INDEX object_status_object ON object_status (object_id, changed_at);

-- Источник ревизии атома или сущности → версия объекта. Пишется вместе с ревизией из её тела (sources[i]),
-- меняется только итог сверки с файлом (уровень 2 автопроверки): verdict, page — где найдена цитата, anchor.
CREATE TABLE source (
    id                  uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    atom_revision_id    uuid REFERENCES atom_revision (id),
    entity_revision_id  uuid REFERENCES entity_revision (id),
    position            integer NOT NULL CHECK (position >= 0),
    object_id           uuid NOT NULL,
    object_version      integer NOT NULL,
    selectors           jsonb,
    quote               text,
    edition_id          uuid REFERENCES entity (id),
    role                text CHECK (role = ANY (ARRAY['primary', 'secondary', 'derived'])),
    verdict             text CHECK (verdict = ANY (ARRAY['ok', 'moved', 'fuzzy', 'by_locator', 'unresolved',
                                                         'not_found', 'no_file', 'no_text', 'external', 'error'])),
    page                integer CHECK (page >= 1),
    anchor              text,
    checked_at          timestamptz,
    FOREIGN KEY (object_id, object_version) REFERENCES object_version (object_id, n),
    CHECK ((atom_revision_id IS NULL) <> (entity_revision_id IS NULL)),
    CHECK ((verdict IS NULL) = (checked_at IS NULL)),
    CHECK (verdict IS NOT NULL OR (page IS NULL AND anchor IS NULL))
);
CREATE UNIQUE INDEX source_atom_position ON source (atom_revision_id, position) WHERE atom_revision_id IS NOT NULL;
CREATE UNIQUE INDEX source_entity_position ON source (entity_revision_id, position)
    WHERE entity_revision_id IS NOT NULL;
CREATE INDEX source_object ON source (object_id, object_version);

-- Неизменность

CREATE FUNCTION amem_source_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amem: источник ревизии нельзя удалить';
    END IF;
    IF (to_jsonb(NEW) - 'verdict' - 'page' - 'anchor' - 'checked_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'verdict' - 'page' - 'anchor' - 'checked_at') THEN
        RAISE EXCEPTION 'amem: источник ревизии нельзя изменить — только итог сверки с файлом';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER source_immutable BEFORE UPDATE OR DELETE ON source
    FOR EACH ROW EXECUTE FUNCTION amem_source_check();
CREATE TRIGGER object_immutable BEFORE UPDATE OR DELETE ON object
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_path_immutable BEFORE UPDATE OR DELETE ON object_path
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_version_immutable BEFORE UPDATE OR DELETE ON object_version
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_status_immutable BEFORE UPDATE OR DELETE ON object_status
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();

CREATE TRIGGER source_no_truncate BEFORE TRUNCATE ON source
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_no_truncate BEFORE TRUNCATE ON object
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_path_no_truncate BEFORE TRUNCATE ON object_path
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_version_no_truncate BEFORE TRUNCATE ON object_version
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER object_status_no_truncate BEFORE TRUNCATE ON object_status
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
