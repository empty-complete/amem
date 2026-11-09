-- Обзор графа (recipes.overview, небо на главной; подпроект 4, часть 4a). Совместимо с PostgreSQL 16.
-- Спецификация: docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md, разд. 3.3 (/graph).
--
-- Обзор проекта начинает с атомов, у ревизии которых scope.project — этот проект: без индекса их ищут проверкой
-- тела каждой текущей ревизии. Частичный — по ревизиям, у которых проект есть; ANALYZE собирает статистику
-- по выражению, и планировщик берёт индекс для редкого проекта. Степень узлов индекса не требует: обзор считает
-- её одним агрегатом по всем текущим рёбрам, а окрестность — по индексам концов link и полей about/derived_from.

CREATE INDEX atom_revision_project ON atom_revision ((payload->'scope'->>'project'))
    WHERE payload->'scope'->>'project' IS NOT NULL;
