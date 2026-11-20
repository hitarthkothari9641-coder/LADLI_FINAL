BEGIN;
CREATE FUNCTION public.ladli_provision_owner(p_username TEXT, p_hash TEXT, p_email TEXT)
RETURNS INTEGER LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE owner_id INTEGER;
BEGIN
  PERFORM pg_advisory_xact_lock(72419301);
  IF EXISTS(SELECT 1 FROM admin_users) THEN
    RAISE EXCEPTION 'An owner already exists; provisioning cannot reset an account';
  END IF;
  IF p_username !~ '^[a-zA-Z0-9_.@-]{3,150}$'
     OR p_hash !~ '^pbkdf2:sha256:1000000\$[a-f0-9]{32}\$[a-f0-9]{64}$'
     OR length(p_email)>255 OR position('@' IN p_email)<2 THEN
    RAISE EXCEPTION 'Invalid owner provisioning data';
  END IF;
  INSERT INTO admin_users(username,password_hash,created_at,must_change_password,email)
    VALUES(p_username,p_hash,CURRENT_TIMESTAMP::text,0,p_email) RETURNING id INTO owner_id;
  INSERT INTO password_history(username,password_hash,changed_at)
    VALUES(p_username,p_hash,CURRENT_TIMESTAMP::text);
  RETURN owner_id;
END;
$$;
REVOKE ALL ON FUNCTION public.ladli_provision_owner(TEXT,TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ladli_provision_owner(TEXT,TEXT,TEXT) TO service_role;
COMMIT;
