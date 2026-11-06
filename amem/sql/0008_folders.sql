-- Папки (подпроект 4, часть 4.0): метаданные записи, как статус, а не ревизия. Совместимо с PostgreSQL 16.
-- Спецификация: docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md, разд. 1.1.
--
-- Путь — сегменты через «/»; правила сегмента (NFC, без управляющих символов, до 100 знаков, до 8 уровней)
-- проверяет amem/folders.py. Здесь — пределы, без которых в столбец попало бы пустое или безразмерное значение:
-- 8 сегментов по 100 знаков и 7 разделителей — 807 знаков, 900 — с запасом.
-- Подборки папку не переносят: это порядок одной базы.

ALTER TABLE atom ADD COLUMN folder text CHECK (folder IS NULL OR (folder <> '' AND length(folder) <= 900));
ALTER TABLE entity ADD COLUMN folder text CHECK (folder IS NULL OR (folder <> '' AND length(folder) <= 900));
CREATE INDEX atom_folder ON atom (folder);
CREATE INDEX entity_folder ON entity (folder);

-- Реестр папок: в нём живут и пустые папки. Путь записи и его родители попадают сюда при переносе;
-- удаляется только пустая папка (amem/folders.py), поэтому триггеров неизменяемости нет.
CREATE TABLE folder (
    path        text PRIMARY KEY CHECK (path <> '' AND length(path) <= 900),
    created_at  timestamptz NOT NULL,
    created_by  text NOT NULL REFERENCES agent (id)
);

-- Журнал переносов: кто, когда, откуда и куда переложил запись (NULL — «без папки»). Только добавление, как status_log.
CREATE TABLE folder_log (
    id           uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    target       text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id    uuid NOT NULL,
    folder_from  text,
    folder_to    text,
    agent        text NOT NULL REFERENCES agent (id),
    changed_at   timestamptz NOT NULL,
    CHECK (folder_from IS DISTINCT FROM folder_to)
);
-- по нему records._lock находит время последнего переноса записи
CREATE INDEX folder_log_record ON folder_log (record_id, changed_at);

CREATE TRIGGER folder_log_immutable BEFORE UPDATE OR DELETE ON folder_log
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER folder_log_no_truncate BEFORE TRUNCATE ON folder_log
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
