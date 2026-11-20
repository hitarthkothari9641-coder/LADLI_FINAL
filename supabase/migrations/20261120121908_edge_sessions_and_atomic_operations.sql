BEGIN;

CREATE TABLE public.admin_sessions (
    token_hash TEXT PRIMARY KEY,
    admin_user_id INTEGER NOT NULL REFERENCES public.admin_users(id) ON DELETE CASCADE,
    password_fingerprint TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX admin_sessions_expiry ON public.admin_sessions(expires_at);
ALTER TABLE public.admin_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.admin_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.admin_sessions TO service_role;

-- All operations run with the caller's privileges. Only the trusted server
-- role can invoke them; none is a public Data API endpoint.
CREATE FUNCTION public.ladli_admit(p_bucket TEXT, p_limit INTEGER, p_window INTEGER)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE n BIGINT;
BEGIN
    IF length(p_bucket) <> 64 OR p_limit < 1 OR p_window < 1 OR p_window > 86400 THEN
        RAISE EXCEPTION 'Invalid admission parameters';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_bucket, 0));
    DELETE FROM request_rate_limits WHERE attempted_at < CURRENT_TIMESTAMP - INTERVAL '1 day';
    SELECT count(*) INTO n FROM request_rate_limits
      WHERE bucket = p_bucket AND attempted_at > CURRENT_TIMESTAMP - make_interval(secs => p_window);
    IF n >= p_limit THEN RETURN false; END IF;
    INSERT INTO request_rate_limits(bucket) VALUES (p_bucket);
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.ladli_admit(TEXT, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_admit(TEXT, INTEGER, INTEGER) TO service_role;

CREATE FUNCTION public.ladli_visit(p_token TEXT DEFAULT NULL)
RETURNS JSONB LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE is_new BOOLEAN := false; total BIGINT; settings visitor_stats%ROWTYPE;
BEGIN
    IF p_token IS NOT NULL THEN
        IF length(p_token) <> 64 THEN RAISE EXCEPTION 'Invalid visitor token'; END IF;
        INSERT INTO unique_visitors(visitor_token, first_seen, last_seen)
          VALUES (p_token, CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text)
          ON CONFLICT (visitor_token) DO UPDATE SET last_seen = EXCLUDED.last_seen
          RETURNING (xmax = 0) INTO is_new;
    END IF;
    SELECT * INTO STRICT settings FROM visitor_stats WHERE id = 1;
    SELECT count(*) INTO total FROM unique_visitors;
    RETURN jsonb_build_object('ok',true,'new_visitor',is_new,'unique_count',total,
      'manual_count',settings.manual_count,'mode',settings.mode,'updated_at',settings.updated_at,
      'count',CASE settings.mode WHEN 'hidden' THEN NULL WHEN 'manual' THEN settings.manual_count ELSE total END);
END;
$$;
REVOKE ALL ON FUNCTION public.ladli_visit(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_visit(TEXT) TO service_role;

CREATE FUNCTION public.ladli_change_password(p_user INTEGER, p_expected_hash TEXT, p_new_hash TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE current_hash TEXT; who TEXT;
BEGIN
    SELECT username,password_hash INTO who,current_hash FROM admin_users WHERE id=p_user FOR UPDATE;
    IF NOT FOUND OR current_hash <> p_expected_hash THEN RETURN false; END IF;
    UPDATE admin_users SET password_hash=p_new_hash,must_change_password=0 WHERE id=p_user;
    INSERT INTO password_history(username,password_hash,changed_at)
      VALUES (who,p_new_hash,CURRENT_TIMESTAMP::text);
    DELETE FROM password_history WHERE username=who AND id NOT IN
      (SELECT id FROM password_history WHERE username=who ORDER BY id DESC LIMIT 5);
    UPDATE password_reset_tokens SET used=1 WHERE username=who;
    DELETE FROM login_attempts WHERE lower(username)=lower(who);
    DELETE FROM admin_sessions WHERE admin_user_id=p_user;
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.ladli_change_password(INTEGER,TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_change_password(INTEGER,TEXT,TEXT) TO service_role;

CREATE FUNCTION public.ladli_set_questions(p_user INTEGER, p_expected_hash TEXT, p_answers JSONB, p_setup_only BOOLEAN)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE owner admin_users%ROWTYPE; answer JSONB;
BEGIN
    SELECT * INTO owner FROM admin_users WHERE id=p_user FOR UPDATE;
    IF NOT FOUND OR owner.password_hash <> p_expected_hash THEN RETURN false; END IF;
    IF p_setup_only AND owner.security_setup_completed=1 THEN RETURN false; END IF;
    IF jsonb_typeof(p_answers) <> 'array' OR jsonb_array_length(p_answers) <> 3 THEN
      RAISE EXCEPTION 'Exactly three distinct questions required';
    END IF;
    IF (SELECT count(DISTINCT (a->>'question_id')::integer) FROM jsonb_array_elements(p_answers) a) <> 3 THEN
      RAISE EXCEPTION 'Exactly three distinct questions required';
    END IF;
    DELETE FROM admin_security_answers WHERE admin_user_id=p_user;
    FOR answer IN SELECT * FROM jsonb_array_elements(p_answers) LOOP
      IF coalesce(length(answer->>'answer_hash'),0)<32 THEN RAISE EXCEPTION 'Invalid answer hash'; END IF;
      INSERT INTO admin_security_answers(admin_user_id,question_id,answer_hash,created_at)
        VALUES(p_user,(answer->>'question_id')::integer,answer->>'answer_hash',CURRENT_TIMESTAMP::text);
    END LOOP;
    UPDATE admin_users SET security_setup_completed=1 WHERE id=p_user;
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.ladli_set_questions(INTEGER,TEXT,JSONB,BOOLEAN) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_set_questions(INTEGER,TEXT,JSONB,BOOLEAN) TO service_role;

CREATE FUNCTION public.ladli_login_locked(p_username TEXT, p_ip TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public, pg_catalog AS $$
  SELECT count(*) >= 5 FROM login_attempts
    WHERE (username=lower(p_username) OR ip_address=p_ip) AND success=0
    AND attempted_at::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '15 minutes';
$$;
REVOKE ALL ON FUNCTION public.ladli_login_locked(TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_login_locked(TEXT,TEXT) TO service_role;

COMMIT;
