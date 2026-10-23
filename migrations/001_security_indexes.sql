CREATE INDEX IF NOT EXISTS login_attempts_username_time ON login_attempts (username, attempted_at);
CREATE INDEX IF NOT EXISTS login_attempts_ip_time ON login_attempts (ip_address, attempted_at);
CREATE INDEX IF NOT EXISTS recovery_attempts_username_time ON recovery_attempts (lower(username), attempted_at);
CREATE INDEX IF NOT EXISTS recovery_attempts_ip_time ON recovery_attempts (ip_address, attempted_at);
CREATE INDEX IF NOT EXISTS password_history_username_id ON password_history (username, id DESC);
CREATE INDEX IF NOT EXISTS reset_tokens_username ON password_reset_tokens (username);
