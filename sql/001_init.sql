-- 001: documents pipeline. Applied by scripts/migrate.sh with psql vars :app_user / :app_password.

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

-- One row per distinct file: sha256 of the bytes is the idempotency key (the same PDF sent twice,
-- by mail and by Telegram, is one document).
CREATE TABLE documents (
    id                bigserial   PRIMARY KEY,
    sha256            text        NOT NULL UNIQUE,
    source            text        NOT NULL CHECK (source IN ('email', 'telegram', 'api')),
    source_ref        text,                            -- Message-ID / chat:message id
    sender            text,                            -- e-mail address / telegram user id
    filename          text,
    mime              text        NOT NULL,
    size_bytes        int         NOT NULL,
    object_key        text        NOT NULL,             -- s3://<bucket>/<object_key>
    status            text        NOT NULL DEFAULT 'new' CHECK (status IN (
                          'new', 'processing', 'auto', 'review', 'approved', 'rejected', 'posted', 'failed', 'skipped')),
    attempt_count     int         NOT NULL DEFAULT 0,
    next_attempt_at   timestamptz NOT NULL DEFAULT now(),
    locked_at         timestamptz,
    last_error        text,
    doc_type          text        CHECK (doc_type IN ('invoice', 'act', 'upd', 'contract', 'other')),
    class_confidence  numeric(4, 3),
    extracted         jsonb,                            -- validated against schemas/<doc_type>.schema.json
    validation        jsonb,                            -- deterministic checks, see services/extractor/app/validate.py
    decision          text        CHECK (decision IN ('auto', 'review')),
    tokens_in         int         NOT NULL DEFAULT 0,
    tokens_out        int         NOT NULL DEFAULT 0,
    cost_rub          numeric(10, 4) NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    processed_at      timestamptz
);
CREATE INDEX documents_pending_idx ON documents (next_attempt_at) WHERE status IN ('new', 'failed', 'processing');
-- business duplicate: the same supplier document under different bytes (re-scan, re-export)
CREATE INDEX documents_business_key_idx ON documents ((extracted->>'supplier_inn'), (extracted->>'number'), (extracted->>'date'));

CREATE TABLE document_text (
    doc_id          bigint      PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    method          text        NOT NULL CHECK (method IN ('pdf_text', 'ocr')),
    pages           int         NOT NULL,
    chars           int         NOT NULL,
    ocr_confidence  numeric(5, 2),                     -- mean tesseract word confidence, 0..100
    text            text        NOT NULL,
    extracted_at    timestamptz NOT NULL DEFAULT now()
);

-- Every LLM call: what it cost and how long it took (per-document limits are enforced from here).
CREATE TABLE llm_calls (
    id           bigserial   PRIMARY KEY,
    doc_id       bigint      REFERENCES documents (id) ON DELETE CASCADE,
    at           timestamptz NOT NULL DEFAULT now(),
    provider     text        NOT NULL,
    model        text,
    task         text        NOT NULL CHECK (task IN ('classify', 'extract', 'repair')),
    tokens_in    int         NOT NULL DEFAULT 0,
    tokens_out   int         NOT NULL DEFAULT 0,
    cost_rub     numeric(10, 4) NOT NULL DEFAULT 0,
    duration_ms  int,
    ok           boolean     NOT NULL,
    error        text
);
CREATE INDEX llm_calls_doc_idx ON llm_calls (doc_id);

-- Who did what with a document and why (system decisions, human confirmations in Telegram).
CREATE TABLE audit_log (
    id         bigserial   PRIMARY KEY,
    doc_id     bigint      REFERENCES documents (id) ON DELETE CASCADE,
    at         timestamptz NOT NULL DEFAULT now(),
    actor      text        NOT NULL,                    -- 'system' | 'tg:<user id>' | workflow name
    action     text        NOT NULL,
    detail     jsonb       NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_doc_idx ON audit_log (doc_id);

CREATE TABLE errors (
    id              bigserial   PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    workflow_id     text,
    workflow_name   text,
    execution_id    text,
    execution_url   text,
    node_name       text,
    error_message   text,
    error_stack     text,
    context         jsonb
);
CREATE INDEX errors_recent_idx ON errors (workflow_id, occurred_at DESC);

CREATE TABLE settings (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO settings (key, value) VALUES
    ('llm_max_tokens_per_doc',   '24000'),   -- in + out, all calls of one document
    ('llm_max_cost_rub_per_doc', '3.00'),
    ('auto_min_class_conf',      '0.80'),    -- below: human review
    ('process_batch_size',       '3'),
    ('process_max_in_flight',    '3'),       -- OCR is CPU-heavy on a 1 vCPU VPS
    ('process_max_attempts',     '4'),
    ('alert_suppress_after',     '3'),
    ('alert_window_min',         '5');

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
