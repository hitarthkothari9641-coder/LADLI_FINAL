CREATE TABLE IF NOT EXISTS request_rate_limits (
    bucket VARCHAR(64) NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS request_rate_limits_bucket_time ON request_rate_limits (bucket, attempted_at);
CREATE INDEX IF NOT EXISTS request_rate_limits_time ON request_rate_limits (attempted_at);
