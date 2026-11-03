-- Движок: производная поисковая проекция, вектора ревизий и журналы полезности.
-- Спецификация: docs/superpowers/specs/2026-11-03-amem-subproject-2-engine-design.md.
-- Вектора принадлежат ревизии и модели; очки принадлежат атому и переживают его правки.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE search_document (
    target        text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id     uuid NOT NULL,
    revision_id   uuid NOT NULL,
    content_hash  text NOT NULL CHECK (content_hash ~ '^sha256-c[1-9][0-9]*:[0-9a-f]{64}$'),
    document      text NOT NULL,
    search_vector tsvector NOT NULL,
    codes         text[] NOT NULL DEFAULT '{}',
    updated_at    timestamptz NOT NULL,
    PRIMARY KEY (target, record_id),
    UNIQUE (target, revision_id)
);

CREATE INDEX search_document_fts ON search_document USING gin (search_vector);
CREATE INDEX search_document_codes ON search_document USING gin (codes);

-- GIN по массиву даёт точное совпадение элемента; для префикса нужна отдельная строка и B-tree.
CREATE TABLE search_code (
    target    text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id uuid NOT NULL,
    code      text NOT NULL CHECK (btrim(code) <> ''),
    PRIMARY KEY (target, record_id, code)
);

CREATE INDEX search_code_exact ON search_code (code);
CREATE INDEX search_code_prefix ON search_code (code text_pattern_ops);

CREATE TABLE embedding_model (
    id         uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    name       text NOT NULL,
    version    text NOT NULL,
    dims       integer NOT NULL CHECK (dims > 0),
    backend    text NOT NULL,
    active     boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    UNIQUE (name, version, backend)
);

CREATE UNIQUE INDEX embedding_model_one_active ON embedding_model (active) WHERE active;

CREATE TABLE embedding (
    target      text NOT NULL CHECK (target IN ('atom', 'entity')),
    revision_id uuid NOT NULL,
    model_id    uuid NOT NULL REFERENCES embedding_model (id),
    dims        integer NOT NULL CHECK (dims > 0),
    text_hash   text NOT NULL,
    vec         halfvec NOT NULL,
    created_at  timestamptz NOT NULL,
    PRIMARY KEY (target, revision_id, model_id)
);

CREATE INDEX embedding_model_revision ON embedding (model_id, revision_id);
CREATE INDEX embedding_hnsw_384 ON embedding USING hnsw
    ((vec::halfvec(384)) halfvec_cosine_ops) WHERE dims = 384;
CREATE INDEX embedding_hnsw_1024 ON embedding USING hnsw
    ((vec::halfvec(1024)) halfvec_cosine_ops) WHERE dims = 1024;

CREATE TABLE retrieval (
    id              uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    activity        uuid REFERENCES activity (id),
    recipe          text NOT NULL,
    query           text NOT NULL,
    agent           text NOT NULL REFERENCES agent (id),
    created_at      timestamptz NOT NULL,
    ranking_version text NOT NULL
);

CREATE INDEX retrieval_activity ON retrieval (activity, created_at);

CREATE TABLE retrieval_item (
    retrieval_id uuid NOT NULL REFERENCES retrieval (id),
    atom_id      uuid NOT NULL REFERENCES atom (id),
    rank         integer NOT NULL CHECK (rank > 0),
    PRIMARY KEY (retrieval_id, atom_id),
    UNIQUE (retrieval_id, rank)
);

CREATE TABLE atom_use (
    id           uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    atom_id      uuid NOT NULL REFERENCES atom (id),
    retrieval_id uuid NOT NULL REFERENCES retrieval (id),
    activity     uuid NOT NULL REFERENCES activity (id),
    agent        text NOT NULL REFERENCES agent (id),
    used_at      timestamptz NOT NULL,
    UNIQUE (activity, atom_id)
);

CREATE INDEX atom_use_score ON atom_use (atom_id, used_at);

CREATE TRIGGER atom_use_immutable BEFORE UPDATE OR DELETE ON atom_use
    FOR EACH ROW EXECUTE FUNCTION amem_forbid_change();
CREATE TRIGGER atom_use_no_truncate BEFORE TRUNCATE ON atom_use
    FOR EACH STATEMENT EXECUTE FUNCTION amem_forbid_change();
