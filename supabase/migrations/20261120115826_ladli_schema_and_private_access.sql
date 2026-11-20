-- LADLI schema snapshot from origin/main 6954bac.
-- Additive bootstrap only: does not import old records or create an admin account.
BEGIN;
SET LOCAL search_path = public;
SELECT pg_advisory_xact_lock(72419301);


CREATE TABLE IF NOT EXISTS admin_users (
    id                       SERIAL PRIMARY KEY,
    username                 VARCHAR(150) UNIQUE NOT NULL,
    password_hash            TEXT NOT NULL,
    created_at               VARCHAR(50) NOT NULL,
    must_change_password     SMALLINT NOT NULL DEFAULT 0,
    email                    VARCHAR(255),
    security_setup_completed SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS password_history (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(150) NOT NULL,
    password_hash TEXT NOT NULL,
    changed_at    VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(150) NOT NULL,
    ip_address   VARCHAR(100) NOT NULL,
    attempted_at VARCHAR(50) NOT NULL,
    success      SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inquiries (
    id                       SERIAL PRIMARY KEY,
    kind                     VARCHAR(50) NOT NULL,
    name                     TEXT,
    company                  TEXT,
    phone                    TEXT,
    email                    TEXT,
    message                  TEXT,
    extra_json               TEXT,
    status                   VARCHAR(50) NOT NULL DEFAULT 'new',
    created_at               VARCHAR(50) NOT NULL,
    attachment_filename      TEXT,
    attachment_original_name TEXT,
    attachment_size_bytes    BIGINT,
    s3_object_key            TEXT
);

CREATE TABLE IF NOT EXISTS visitor_stats (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    manual_count INTEGER NOT NULL DEFAULT 0,
    mode         VARCHAR(50) NOT NULL DEFAULT 'auto',
    updated_at   VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS unique_visitors (
    visitor_token VARCHAR(128) PRIMARY KEY,
    first_seen    VARCHAR(50) NOT NULL,
    last_seen     VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS security_questions (
    id       SERIAL PRIMARY KEY,
    question TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS admin_security_answers (
    id            SERIAL PRIMARY KEY,
    admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    question_id   INTEGER NOT NULL REFERENCES security_questions(id),
    answer_hash   TEXT NOT NULL,
    created_at    VARCHAR(50) NOT NULL,
    UNIQUE(admin_user_id, question_id)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(150) NOT NULL,
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     VARCHAR(50) NOT NULL,
    expires_at     VARCHAR(50) NOT NULL,
    used           SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recovery_attempts (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(150) NOT NULL,
    ip_address   VARCHAR(100) NOT NULL,
    attempted_at VARCHAR(50) NOT NULL,
    success      SMALLINT NOT NULL DEFAULT 0
);


CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);

-- Existing application migration: 001_security_indexes

CREATE INDEX IF NOT EXISTS login_attempts_username_time ON login_attempts (username, attempted_at);
CREATE INDEX IF NOT EXISTS login_attempts_ip_time ON login_attempts (ip_address, attempted_at);
CREATE INDEX IF NOT EXISTS recovery_attempts_username_time ON recovery_attempts (lower(username), attempted_at);
CREATE INDEX IF NOT EXISTS recovery_attempts_ip_time ON recovery_attempts (ip_address, attempted_at);
CREATE INDEX IF NOT EXISTS password_history_username_id ON password_history (username, id DESC);
CREATE INDEX IF NOT EXISTS reset_tokens_username ON password_reset_tokens (username);


INSERT INTO schema_migrations (version) VALUES ('001_security_indexes') ON CONFLICT (version) DO NOTHING;

-- Existing application migration: 002_shared_rate_limits

CREATE TABLE IF NOT EXISTS request_rate_limits (
    bucket VARCHAR(64) NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS request_rate_limits_bucket_time ON request_rate_limits (bucket, attempted_at);
CREATE INDEX IF NOT EXISTS request_rate_limits_time ON request_rate_limits (attempted_at);


INSERT INTO schema_migrations (version) VALUES ('002_shared_rate_limits') ON CONFLICT (version) DO NOTHING;

INSERT INTO visitor_stats (id, manual_count, mode, updated_at) VALUES (1, 0, 'auto', CURRENT_TIMESTAMP::text) ON CONFLICT (id) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What is the name of your first pet?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('In what city were you born?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What is your mother''s maiden name?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What was the name of your first school?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What is your favorite movie?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What was the make of your first car?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What is your favorite book?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What street did you grow up on?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What is the name of your childhood best friend?') ON CONFLICT (question) DO NOTHING;

INSERT INTO security_questions (question) VALUES ('What was your first job title?') ON CONFLICT (question) DO NOTHING;

ALTER TABLE public.admin_security_answers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.admin_security_answers FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.admin_security_answers TO service_role;

ALTER TABLE public.admin_users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.admin_users FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.admin_users TO service_role;

ALTER TABLE public.inquiries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.inquiries FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.inquiries TO service_role;

ALTER TABLE public.login_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.login_attempts FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.login_attempts TO service_role;

ALTER TABLE public.password_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.password_history FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.password_history TO service_role;

ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.password_reset_tokens FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.password_reset_tokens TO service_role;

ALTER TABLE public.recovery_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.recovery_attempts FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.recovery_attempts TO service_role;

ALTER TABLE public.request_rate_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.request_rate_limits FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.request_rate_limits TO service_role;

ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.schema_migrations FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.schema_migrations TO service_role;

ALTER TABLE public.security_questions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.security_questions FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.security_questions TO service_role;

ALTER TABLE public.unique_visitors ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.unique_visitors FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.unique_visitors TO service_role;

ALTER TABLE public.visitor_stats ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.visitor_stats FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.visitor_stats TO service_role;

REVOKE ALL ON SEQUENCE public.admin_users_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.admin_users_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.password_history_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.password_history_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.login_attempts_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.login_attempts_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.inquiries_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.inquiries_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.security_questions_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.security_questions_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.admin_security_answers_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.admin_security_answers_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.password_reset_tokens_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.password_reset_tokens_id_seq TO service_role;

REVOKE ALL ON SEQUENCE public.recovery_attempts_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.recovery_attempts_id_seq TO service_role;

COMMIT;
