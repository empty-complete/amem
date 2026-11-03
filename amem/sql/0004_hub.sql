-- Задел под хаб баз: идентичность базы и метаданные. base_id пишет db.prepare (UUIDv7, один раз);
-- происхождение атомов при переносе — provenance.origin_base в теле ревизии (amem/schema/amem_v1.yaml).
CREATE TABLE meta (
    key     text PRIMARY KEY,
    value   jsonb NOT NULL
);
