-- Ядро схемы v1: словари, шаблоны, пакеты изменений, сущности, атомы, связи.
-- Спецификация: docs/superpowers/specs/2026-10-19-schema-v1-postgres-reatomize-design.md, разд. 1–2.
--
-- Совместимо с PostgreSQL 16: без uuidv7() (id ставит сервер, atomgraph/ids.py) и без WITHOUT OVERLAPS
-- (сроки редакций — EXCLUDE USING gist с btree_gist). Перечни в CHECK совпадают с перечислениями
-- atomgraph/schema/amem_v1.yaml — это проверяет tests/test_sql_schema.py.
--
-- Ничего не удаляется: ревизии, пакеты, журнал статусов и связи защищены триггерами, и от TRUNCATE тоже.
-- Обойти их может только владелец таблиц (DISABLE TRIGGER) — у приложения должна быть своя роль без этих прав.
-- У ревизии меняется только решение проверки (pending → accepted / declined), у связи — только вывод из оборота.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE concept (
    scheme      text NOT NULL,
    code        text NOT NULL,
    data        jsonb NOT NULL,              -- понятие целиком, в формате model_v1.Concept
    origin      text NOT NULL CHECK (origin IN ('schema', 'vocab', 'agent')),
    updated_at  timestamptz NOT NULL,
    PRIMARY KEY (scheme, code)
);

CREATE TABLE template (
    code        text NOT NULL,
    version     text NOT NULL,
    target      text NOT NULL CHECK (target IN ('atom', 'entity', 'link')),
    applies_to  text,
    body        jsonb NOT NULL,
    body_hash   text NOT NULL,
    loaded_at   timestamptz NOT NULL,
    PRIMARY KEY (code, version)
);

CREATE TABLE agent (
    id    text PRIMARY KEY CHECK (id ~ '^(person|model):[a-z0-9_.-]+$'),
    name  text
);

CREATE TABLE activity (
    id          uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    kind        text NOT NULL CHECK (kind IN ('task', 'wave', 'session', 'migration')),
    label       text,
    started_at  timestamptz NOT NULL,
    ended_at    timestamptz
);

CREATE TABLE changeset (
    id            uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    agent         text NOT NULL REFERENCES agent (id),
    activity      uuid REFERENCES activity (id),
    reason        text,
    state         text NOT NULL CHECK (state IN ('approved', 'rejected')),
    check_report  jsonb,
    created_at    timestamptz NOT NULL
);

-- Запись (entity, atom) — неизменный id и проекция текущей ревизии: key, класс или вид, статус.
CREATE TABLE entity (
    id                 uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    key                text UNIQUE,
    entity_class       text NOT NULL CHECK (entity_class IN (
                           'project', 'building', 'system', 'product', 'assembly', 'component', 'fastener',
                           'material', 'standard', 'edition', 'document', 'organization', 'place', 'software')),
    status             text NOT NULL CHECK (status IN (
                           'draft', 'needs_review', 'auto_verified', 'verified', 'rejected', 'deprecated', 'superseded')),
    created_at         timestamptz NOT NULL,
    status_changed_at  timestamptz NOT NULL
);

CREATE TABLE entity_revision (
    id              uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    entity_id       uuid NOT NULL REFERENCES entity (id),
    n               integer NOT NULL CHECK (n >= 1),
    schema_version  text NOT NULL,
    payload         jsonb NOT NULL,          -- каноническое тело (atomgraph/canon.py)
    content_hash    text NOT NULL CHECK (content_hash ~ '^sha256-c[1-9][0-9]*:[0-9a-f]{64}$'),
    changeset_id    uuid NOT NULL REFERENCES changeset (id),
    valid_from      date,
    valid_to        date,
    recorded_at     timestamptz NOT NULL,
    review_state    text NOT NULL CHECK (review_state IN ('none', 'pending', 'accepted', 'declined')),
    reviewed_by     text REFERENCES agent (id),
    reviewed_at     timestamptz,
    UNIQUE (entity_id, n),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
    -- автор и время решения есть ровно у принятых и отклонённых ревизий
    CHECK ((reviewed_by IS NOT NULL) = (review_state = 'accepted' OR review_state = 'declined')
           AND (reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CHECK (reviewed_at IS NULL OR reviewed_at >= recorded_at)
);

CREATE TABLE atom (
    id                 uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    key                text UNIQUE,
    kind               text NOT NULL CHECK (kind IN (
                           'fact', 'norm', 'requirement', 'formula', 'parameter', 'term', 'method',
                           'calculation', 'decision', 'question', 'lesson')),
    status             text NOT NULL CHECK (status IN (
                           'draft', 'needs_review', 'auto_verified', 'verified', 'rejected', 'deprecated', 'superseded')),
    created_at         timestamptz NOT NULL,
    status_changed_at  timestamptz NOT NULL
);

CREATE TABLE atom_revision (
    id              uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    atom_id         uuid NOT NULL REFERENCES atom (id),
    n               integer NOT NULL CHECK (n >= 1),
    schema_version  text NOT NULL,
    payload         jsonb NOT NULL,
    content_hash    text NOT NULL CHECK (content_hash ~ '^sha256-c[1-9][0-9]*:[0-9a-f]{64}$'),
    changeset_id    uuid NOT NULL REFERENCES changeset (id),
    valid_from      date,
    valid_to        date,
    recorded_at     timestamptz NOT NULL,
    review_state    text NOT NULL CHECK (review_state IN ('none', 'pending', 'accepted', 'declined')),
    reviewed_by     text REFERENCES agent (id),
    reviewed_at     timestamptz,
    UNIQUE (atom_id, n),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
    CHECK ((reviewed_by IS NOT NULL) = (review_state = 'accepted' OR review_state = 'declined')
           AND (reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CHECK (reviewed_at IS NULL OR reviewed_at >= recorded_at)
);

-- Текущая ревизия: последняя с review_state none или accepted; если таких нет — последняя pending.
-- Отклонённые (declined) текущими не бывают.
CREATE VIEW entity_current AS
    SELECT DISTINCT ON (entity_id) *
    FROM entity_revision
    WHERE review_state <> 'declined'
    ORDER BY entity_id, (review_state = 'pending'), n DESC;

CREATE VIEW atom_current AS
    SELECT DISTINCT ON (atom_id) *
    FROM atom_revision
    WHERE review_state <> 'declined'
    ORDER BY atom_id, (review_state = 'pending'), n DESC;

-- Поля-ссылки ревизии атома, разложенные для поиска по графу; внешние ключи проверяют, что цель есть.
CREATE TABLE atom_about (
    revision_id  uuid NOT NULL REFERENCES atom_revision (id),
    entity_id    uuid NOT NULL REFERENCES entity (id),
    PRIMARY KEY (revision_id, entity_id)
);
CREATE INDEX atom_about_entity ON atom_about (entity_id);

CREATE TABLE atom_derived (
    revision_id  uuid NOT NULL REFERENCES atom_revision (id),
    atom_id      uuid NOT NULL REFERENCES atom (id),
    PRIMARY KEY (revision_id, atom_id)
);
CREATE INDEX atom_derived_atom ON atom_derived (atom_id);

-- Срок действия редакций — проекция текущей ревизии сущности класса edition.
-- Редакция без даты начала (valid IS NULL) в проверке пересечений и в запросе «на дату» не участвует.
CREATE TABLE edition (
    entity_id   uuid PRIMARY KEY REFERENCES entity (id),
    edition_of  uuid NOT NULL REFERENCES entity (id),
    valid       daterange CHECK (NOT isempty(valid)),
    CHECK (edition_of <> entity_id),
    EXCLUDE USING gist (edition_of WITH =, valid WITH &&)
);

CREATE TABLE link (
    id            uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    rel           text NOT NULL CHECK (rel IN (
                      'part_of', 'governed_by', 'computed_by', 'used_in', 'attached_to', 'made_of', 'depends_on',
                      'refines', 'supersedes', 'contradicts', 'example_of', 'answers', 'same_as', 'see_also')),
    src_atom      uuid REFERENCES atom (id),
    src_entity    uuid REFERENCES entity (id),
    dst_atom      uuid REFERENCES atom (id),
    dst_entity    uuid REFERENCES entity (id),
    note          jsonb,
    qualifiers    jsonb,
    confidence    real CHECK (confidence BETWEEN 0 AND 1),
    changeset_id  uuid NOT NULL REFERENCES changeset (id),
    agent         text NOT NULL REFERENCES agent (id),
    created_at    timestamptz NOT NULL,
    retired_at    timestamptz,
    retired_by    uuid REFERENCES changeset (id),
    CHECK (num_nonnulls(src_atom, src_entity) = 1),
    CHECK (num_nonnulls(dst_atom, dst_entity) = 1),
    CHECK ((retired_at IS NULL) = (retired_by IS NULL)),
    CHECK (retired_at IS NULL OR retired_at >= created_at),
    CHECK (coalesce(src_atom, src_entity) <> coalesce(dst_atom, dst_entity))
);
CREATE INDEX link_src ON link (coalesce(src_atom, src_entity));
CREATE INDEX link_dst ON link (coalesce(dst_atom, dst_entity));
-- одна действующая связь одного вида между двумя записями; выведенные из оборота не мешают.
-- У симметричных связей (словарь rel, symmetric) A→B и B→A — одна связь: концы берутся по порядку.
CREATE UNIQUE INDEX link_active ON link (
    rel,
    (CASE WHEN rel IN ('contradicts', 'same_as', 'see_also')
          THEN least(coalesce(src_atom, src_entity), coalesce(dst_atom, dst_entity))
          ELSE coalesce(src_atom, src_entity) END),
    (CASE WHEN rel IN ('contradicts', 'same_as', 'see_also')
          THEN greatest(coalesce(src_atom, src_entity), coalesce(dst_atom, dst_entity))
          ELSE coalesce(dst_atom, dst_entity) END))
    WHERE retired_at IS NULL;

-- Журнал статусов атомов и сущностей: «какой статус был на дату» и кто его поставил.
CREATE TABLE status_log (
    id          uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    target      text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id   uuid NOT NULL,
    status      text NOT NULL CHECK (status IN (
                    'draft', 'needs_review', 'auto_verified', 'verified', 'rejected', 'deprecated', 'superseded')),
    agent       text NOT NULL REFERENCES agent (id),
    reason      text,
    changed_at  timestamptz NOT NULL
);
CREATE INDEX status_log_record ON status_log (record_id, changed_at);

-- Неизменность

CREATE FUNCTION amem_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'amem: % в таблице % запрещено — записи не меняются и не удаляются', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE FUNCTION amem_revision_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amem: ревизию нельзя удалить (%)', TG_TABLE_NAME;
    END IF;
    IF (to_jsonb(NEW) - 'review_state' - 'reviewed_by' - 'reviewed_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'review_state' - 'reviewed_by' - 'reviewed_at') THEN
        RAISE EXCEPTION 'amem: ревизию нельзя изменить — только решение проверки (%)', TG_TABLE_NAME;
    END IF;
    IF OLD.review_state <> 'pending' OR NEW.review_state NOT IN ('accepted', 'declined')
       OR NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL THEN
        RAISE EXCEPTION 'amem: решение проверки — только pending → accepted / declined, с автором и временем';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION amem_link_retire() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'amem: связь нельзя удалить — только вывести из оборота';
    END IF;
    IF (to_jsonb(NEW) - 'retired_at' - 'retired_by') IS DISTINCT FROM (to_jsonb(OLD) - 'retired_at' - 'retired_by') THEN
        RAISE EXCEPTION 'amem: связь нельзя изменить — только вывести из оборота';
    END IF;
    IF OLD.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'amem: связь уже выведена из оборота';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER entity_revision_immutable BEFORE UPDATE OR DELETE ON entity_revision
    FOR EACH ROW EXECUTE FUNCTION amem_revision_review();
CREATE TRIGGER atom_revision_immutable BEFORE UPDATE OR DELETE ON atom_revision
    FOR EACH ROW EXECUTE FUNCTION amem_revision_review();
CREATE TRIGGER link_immutable BEFORE UPDATE OR DELETE ON link
    FOR EACH ROW EXECUTE FUNCTION amem_link_retire();
CREATE TRIGGER changeset_immutable BEFORE UPDATE OR DELETE ON changeset
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER status_log_immutable BEFORE UPDATE OR DELETE ON status_log
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_about_immutable BEFORE UPDATE OR DELETE ON atom_about
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_derived_immutable BEFORE UPDATE OR DELETE ON atom_derived
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER template_immutable BEFORE UPDATE OR DELETE ON template
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();

-- TRUNCATE — тоже удаление, и строчные триггеры его не видят
CREATE TRIGGER entity_revision_no_truncate BEFORE TRUNCATE ON entity_revision
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_revision_no_truncate BEFORE TRUNCATE ON atom_revision
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER link_no_truncate BEFORE TRUNCATE ON link
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER changeset_no_truncate BEFORE TRUNCATE ON changeset
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER status_log_no_truncate BEFORE TRUNCATE ON status_log
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_about_no_truncate BEFORE TRUNCATE ON atom_about
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_derived_no_truncate BEFORE TRUNCATE ON atom_derived
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER template_no_truncate BEFORE TRUNCATE ON template
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
