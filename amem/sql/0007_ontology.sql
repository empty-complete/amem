-- Схема v1, часть 3c: зависимости пакетов, проекция величин атома, история импорта. Совместимо с PostgreSQL 16.

-- Зависимости пакета: имя → диапазон версий (packaging.SpecifierSet). Проверяет packs.load_packs до записи в базу.
ALTER TABLE pack ADD COLUMN requires jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Величины текущей ревизии атома: content.values[].property. Заполняется записью ревизии (amem/records.py)
-- вместе с atom_about; перестраивается records.rebuild_projections.
-- Производная проекция, как search_document: триггеров неизменяемости нет — её можно стереть и построить заново.
-- Внешнего ключа на concept нет намеренно: коды величин свободны (неизвестный код — предупреждение
-- unknown_property уровня 3, спецификация подпроекта 3, разд. 6), иначе запись такого атома упала бы.
CREATE TABLE atom_property (
    revision_id  uuid NOT NULL REFERENCES atom_revision (id),
    property     text NOT NULL,
    PRIMARY KEY (revision_id, property)
);
CREATE INDEX atom_property_property ON atom_property (property, revision_id);

-- Ревизии чужой базы, пришедшие подборкой с историей: локальной историей не становятся, хранятся для просмотра.
CREATE TABLE import_history (
    id            uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    changeset_id  uuid NOT NULL REFERENCES changeset (id),
    target        text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id     uuid NOT NULL,
    origin_base   uuid NOT NULL,
    n             integer NOT NULL CHECK (n >= 1),
    content_hash  text NOT NULL,
    payload       jsonb NOT NULL,
    recorded_at   timestamptz NOT NULL,
    agent         text,
    UNIQUE (origin_base, record_id, n)
);
CREATE INDEX import_history_record ON import_history (record_id, n);
-- журнал: только добавление
CREATE TRIGGER import_history_immutable BEFORE UPDATE OR DELETE ON import_history
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER import_history_no_truncate BEFORE TRUNCATE ON import_history
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();

-- Новая причина пункта очереди: пришло подборкой из другой базы. 0006 не меняется — её хэш записан в базах.
ALTER TABLE review_item DROP CONSTRAINT review_item_reason_check;
ALTER TABLE review_item ADD CONSTRAINT review_item_reason_check CHECK (reason IN ('semantic', 'warning', 'high_risk',
    'semantic_doubt', 'edit', 'source_changed', 'audit', 'calibration', 'imported'));
