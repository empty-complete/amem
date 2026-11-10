-- Задачи агентам (подпроект 4, часть 4d; спецификация разд. 6a.5): человек или модель ставит задачу о версии
-- объекта («разобрать файл» — kind parse), модель берёт её через MCP с арендой и закрывает с итогом. Совместимо
-- с PostgreSQL 16. Правила переходов (кто берёт, кто отменяет, аренда) — amem/tasks.py; здесь — то, без чего
-- строка была бы бессмысленной.
--
-- state: open — ждёт агента; claimed — взята (claimed_by, claimed_until — аренда; истёкшую берёт другой);
-- done — закрыта агентом, result — что сделано (ссылки записей); cancelled — отменена. done_at — когда закрыта
-- (done или cancelled). claimed_by у закрытой остаётся: кто её делал.
CREATE TABLE task (
    id             uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    kind           text NOT NULL CHECK (kind IN ('parse')),
    object_id      uuid NOT NULL,
    version        integer NOT NULL CHECK (version >= 1),
    note           text CHECK (note IS NULL OR length(note) <= 4000),
    state          text NOT NULL CHECK (state IN ('open', 'claimed', 'done', 'cancelled')),
    created_by     text NOT NULL REFERENCES agent (id),
    created_at     timestamptz NOT NULL,
    claimed_by     text REFERENCES agent (id),
    claimed_until  timestamptz,
    done_at        timestamptz,
    result         jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    FOREIGN KEY (object_id, version) REFERENCES object_version (object_id, n),
    CHECK (state <> 'open' OR (claimed_by IS NULL AND claimed_until IS NULL)),
    CHECK (state <> 'claimed' OR (claimed_by IS NOT NULL AND claimed_until IS NOT NULL)),
    CHECK ((done_at IS NOT NULL) = (state IN ('done', 'cancelled'))),
    CHECK (state = 'done' OR result IS NULL)
);

-- одна незакрытая задача на (вид, объект, версия): повтор постановки возвращает её же
CREATE UNIQUE INDEX task_open ON task (kind, object_id, version) WHERE state IN ('open', 'claimed');
CREATE INDEX task_state_created ON task (state, created_at, id);
CREATE INDEX task_object ON task (object_id, version);
