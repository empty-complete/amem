-- Схема v1, часть 3: автопроверка — активные шаблоны, очередь проверки и вердикты. Совместимо с PostgreSQL 16.

-- Какая версия шаблона действует. Таблица template хранит все загруженные версии навсегда, а проверяет запись
-- только активная: db.load_vocab переписывает эту таблицу из пакетов, которые загружены сейчас.
CREATE TABLE template_active (
    code     text PRIMARY KEY,
    version  text NOT NULL,
    FOREIGN KEY (code, version) REFERENCES template (code, version)
);

-- Очередь проверки: пункт привязан к ревизии (а не к записи), чтобы вердикт относился к тому, что проверяли.
CREATE TABLE review_item (
    id                  uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    target              text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id           uuid NOT NULL,
    atom_revision_id    uuid REFERENCES atom_revision (id),
    entity_revision_id  uuid REFERENCES entity_revision (id),
    reason              text NOT NULL CHECK (reason IN ('semantic', 'warning', 'high_risk', 'semantic_doubt',
                            'edit', 'source_changed', 'audit', 'calibration')),
    state               text NOT NULL CHECK (state IN ('queued', 'claimed', 'done', 'obsolete')),
    changeset_id        uuid REFERENCES changeset (id),
    details             jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL,
    created_by          text NOT NULL REFERENCES agent (id),
    claimed_by          text REFERENCES agent (id),
    claimed_until       timestamptz,
    closed_at           timestamptz,
    CHECK ((atom_revision_id IS NULL) <> (entity_revision_id IS NULL)),
    CHECK ((target = 'atom') = (atom_revision_id IS NOT NULL)),
    CHECK (state <> 'claimed' OR (claimed_by IS NOT NULL AND claimed_until IS NOT NULL)),
    CHECK (state <> 'queued' OR (claimed_by IS NULL AND claimed_until IS NULL)),
    -- без IN: иначе ограничение попадёт под сверку перечня состояний в test_sql_schema
    CHECK ((state = 'done' OR state = 'obsolete') = (closed_at IS NOT NULL))
);
-- открытый пункт на (ревизия, причина) — один: повторная постановка не плодит дубликатов
CREATE UNIQUE INDEX review_item_open ON review_item (coalesce(atom_revision_id, entity_revision_id), reason)
    WHERE state IN ('queued', 'claimed');
CREATE INDEX review_item_state ON review_item (state, reason, created_at);
CREATE INDEX review_item_record ON review_item (record_id);
CREATE INDEX changeset_state_created ON changeset (state, created_at);

-- Вердикт по пункту — неизменяемый; один пункт — один вердикт.
CREATE TABLE verification (
    id              uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    review_item_id  uuid NOT NULL UNIQUE REFERENCES review_item (id),
    method          text NOT NULL CHECK (method IN ('llm_judge', 'human')),
    outcome         text NOT NULL CHECK (outcome IN ('confirmed', 'partial', 'refuted', 'uncertain')),
    confidence      double precision CHECK (confidence >= 0 AND confidence <= 1),
    agent           text NOT NULL REFERENCES agent (id),
    note            text,
    created_at      timestamptz NOT NULL,
    CHECK (method <> 'llm_judge' OR confidence IS NOT NULL),
    CHECK ((method = 'human') = (agent LIKE 'person:%'))
);

-- Неизменность

CREATE FUNCTION amem_review_item_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    owner uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amem: пункт очереди нельзя удалить';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'queued' THEN
            RAISE EXCEPTION 'amem: пункт очереди создаётся в состоянии queued, а не %', NEW.state;
        END IF;
        IF NEW.target = 'atom' THEN
            SELECT atom_id INTO owner FROM atom_revision WHERE id = NEW.atom_revision_id;
        ELSE
            SELECT entity_id INTO owner FROM entity_revision WHERE id = NEW.entity_revision_id;
        END IF;
        IF owner IS DISTINCT FROM NEW.record_id THEN
            RAISE EXCEPTION 'amem: ревизия пункта очереди принадлежит другой записи';
        END IF;
        RETURN NEW;
    END IF;
    -- меняется только ход работы над пунктом: кто взял, до когда, когда закрыт
    IF (to_jsonb(NEW) - 'state' - 'claimed_by' - 'claimed_until' - 'closed_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'state' - 'claimed_by' - 'claimed_until' - 'closed_at') THEN
        RAISE EXCEPTION 'amem: пункт очереди нельзя изменить — только ход работы (состояние, кто взял, срок)';
    END IF;
    IF OLD.state IN ('done', 'obsolete') THEN
        RAISE EXCEPTION 'amem: закрытый пункт очереди (%) не открывается снова', OLD.state;
    END IF;
    IF NOT ((OLD.state = 'queued' AND NEW.state = 'claimed')
            OR (OLD.state = 'claimed' AND NEW.state IN ('claimed', 'queued'))
            OR (OLD.state IN ('queued', 'claimed') AND NEW.state IN ('done', 'obsolete'))) THEN
        RAISE EXCEPTION 'amem: переход пункта очереди % → % не разрешён', OLD.state, NEW.state;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER review_item_check BEFORE INSERT OR UPDATE OR DELETE ON review_item
    FOR EACH ROW EXECUTE FUNCTION amem_review_item_check();
CREATE TRIGGER verification_immutable BEFORE UPDATE OR DELETE ON verification
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();

CREATE TRIGGER review_item_no_truncate BEFORE TRUNCATE ON review_item
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER verification_no_truncate BEFORE TRUNCATE ON verification
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();

-- Сброс кэша: текст docx и xlsx раньше не извлекался (page 0 — «текста нет»); теперь извлекается (amem.extract),
-- а кэш по содержимому иначе навсегда остался бы пустым.
DELETE FROM object_text t USING object_version v, object o
 WHERE t.digest = v.digest AND o.id = v.object_id AND t.page = 0
   AND lower(o.original_name) ~ '\.(docx|xlsx|xlsm)$';
