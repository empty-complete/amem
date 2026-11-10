-- Список записей (lookup.list_records, подпроект 4, часть 4.0). Совместимо с PostgreSQL 16.
-- Спецификация: docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md, разд. 1.2.
--
-- Список — новые сверху по времени показанной ревизии записи. Обход индекса (recorded_at, id записи) с конца
-- отдаёт страницу, не сортируя всю базу; курсор — то же сравнение (recorded_at, id) < (…) по индексу.
-- Тег — фильтр по телу ревизии: GIN по payload->'tags' находит редкий тег без обхода всех ревизий, а ANALYZE
-- собирает по этому выражению статистику — без неё планировщик оценивает @> наугад и выбирает не тот путь.

CREATE INDEX atom_revision_recorded ON atom_revision (recorded_at, atom_id);
CREATE INDEX entity_revision_recorded ON entity_revision (recorded_at, entity_id);
CREATE INDEX atom_revision_tags ON atom_revision USING gin ((payload->'tags') jsonb_path_ops);
