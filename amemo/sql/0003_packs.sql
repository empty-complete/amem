-- Пакеты домена: kind, entity_class и rel — коды понятий из загруженных пакетов, а не перечни в CHECK.
-- Сверка значений — внешний ключ на concept(scheme, code) через служебный столбец схемы с постоянным
-- значением (kind_scheme = 'kind' и т. п.); приложение дополнительно отвечает RecordError (amem/records.py).
-- origin понятия — теперь 'schema' (служебные перечни), 'agent' или имя пакета.

CREATE TABLE pack (
    name        text NOT NULL,
    version     text NOT NULL,
    digest      text NOT NULL,               -- sha256 содержимого пакета: та же версия с другим digest — ошибка
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (name, version)
);

ALTER TABLE concept DROP CONSTRAINT concept_origin_check;

ALTER TABLE atom DROP CONSTRAINT atom_kind_check;
ALTER TABLE atom ADD COLUMN kind_scheme text NOT NULL DEFAULT 'kind' CHECK (kind_scheme = 'kind'),
    ADD CONSTRAINT atom_kind_concept FOREIGN KEY (kind_scheme, kind) REFERENCES concept (scheme, code);

ALTER TABLE entity DROP CONSTRAINT entity_entity_class_check;
ALTER TABLE entity ADD COLUMN entity_class_scheme text NOT NULL DEFAULT 'entity_class' CHECK (entity_class_scheme = 'entity_class'),
    ADD CONSTRAINT entity_class_concept FOREIGN KEY (entity_class_scheme, entity_class) REFERENCES concept (scheme, code);

ALTER TABLE link DROP CONSTRAINT link_rel_check;
ALTER TABLE link ADD COLUMN rel_scheme text NOT NULL DEFAULT 'rel' CHECK (rel_scheme = 'rel'),
    ADD CONSTRAINT link_rel_concept FOREIGN KEY (rel_scheme, rel) REFERENCES concept (scheme, code);
