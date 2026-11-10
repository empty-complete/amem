-- Имя проекта amem → amemo: функции триггеров получают новые имена и сообщения «amemo: …».
-- Миграции 0001–0012 не меняются (база сверяет их по sha256). Триггеры ссылаются на функцию по OID,
-- поэтому переименование их не задевает. Файл создан tools/rename_amemo.py.

ALTER FUNCTION amem_forbid_change() RENAME TO amemo_forbid_change;
ALTER FUNCTION amem_revision_review() RENAME TO amemo_revision_review;
ALTER FUNCTION amem_link_retire() RENAME TO amemo_link_retire;
ALTER FUNCTION amem_source_check() RENAME TO amemo_source_check;
ALTER FUNCTION amem_review_item_check() RENAME TO amemo_review_item_check;

CREATE OR REPLACE FUNCTION amemo_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'amemo: % в таблице % запрещено — записи не меняются и не удаляются', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE OR REPLACE FUNCTION amemo_revision_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amemo: ревизию нельзя удалить (%)', TG_TABLE_NAME;
    END IF;
    IF (to_jsonb(NEW) - 'review_state' - 'reviewed_by' - 'reviewed_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'review_state' - 'reviewed_by' - 'reviewed_at') THEN
        RAISE EXCEPTION 'amemo: ревизию нельзя изменить — только решение проверки (%)', TG_TABLE_NAME;
    END IF;
    IF OLD.review_state <> 'pending' OR NEW.review_state NOT IN ('accepted', 'declined')
       OR NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL THEN
        RAISE EXCEPTION 'amemo: решение проверки — только pending → accepted / declined, с автором и временем';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION amemo_link_retire() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amemo: связь нельзя удалить — только вывести из оборота';
    END IF;
    IF (to_jsonb(NEW) - 'retired_at' - 'retired_by') IS DISTINCT FROM (to_jsonb(OLD) - 'retired_at' - 'retired_by') THEN
        RAISE EXCEPTION 'amemo: связь нельзя изменить — только вывести из оборота';
    END IF;
    IF OLD.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'amemo: связь уже выведена из оборота';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION amemo_source_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amemo: источник ревизии нельзя удалить';
    END IF;
    IF (to_jsonb(NEW) - 'verdict' - 'page' - 'anchor' - 'checked_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'verdict' - 'page' - 'anchor' - 'checked_at') THEN
        RAISE EXCEPTION 'amemo: источник ревизии нельзя изменить — только итог сверки с файлом';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION amemo_review_item_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    owner uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amemo: пункт очереди нельзя удалить';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'queued' THEN
            RAISE EXCEPTION 'amemo: пункт очереди создаётся в состоянии queued, а не %', NEW.state;
        END IF;
        IF NEW.target = 'atom' THEN
            SELECT atom_id INTO owner FROM atom_revision WHERE id = NEW.atom_revision_id;
        ELSE
            SELECT entity_id INTO owner FROM entity_revision WHERE id = NEW.entity_revision_id;
        END IF;
        IF owner IS DISTINCT FROM NEW.record_id THEN
            RAISE EXCEPTION 'amemo: ревизия пункта очереди принадлежит другой записи';
        END IF;
        RETURN NEW;
    END IF;
    -- меняется только ход работы над пунктом: кто взял, до когда, когда закрыт
    IF (to_jsonb(NEW) - 'state' - 'claimed_by' - 'claimed_until' - 'closed_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'state' - 'claimed_by' - 'claimed_until' - 'closed_at') THEN
        RAISE EXCEPTION 'amemo: пункт очереди нельзя изменить — только ход работы (состояние, кто взял, срок)';
    END IF;
    IF OLD.state IN ('done', 'obsolete') THEN
        RAISE EXCEPTION 'amemo: закрытый пункт очереди (%) не открывается снова', OLD.state;
    END IF;
    IF NOT ((OLD.state = 'queued' AND NEW.state = 'claimed')
            OR (OLD.state = 'claimed' AND NEW.state IN ('claimed', 'queued'))
            OR (OLD.state IN ('queued', 'claimed') AND NEW.state IN ('done', 'obsolete'))) THEN
        RAISE EXCEPTION 'amemo: переход пункта очереди % → % не разрешён', OLD.state, NEW.state;
    END IF;
    RETURN NEW;
END
$$;
