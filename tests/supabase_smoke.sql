-- Run after the two Supabase migrations. All fixtures are rolled back.
-- No client records or real credentials are changed. PostgreSQL sequence
-- numbers used by temporary fixture inserts may advance despite rollback.
BEGIN;
SET LOCAL ROLE service_role;
INSERT INTO public.admin_users(id,username,password_hash,created_at,must_change_password)
  VALUES(-2147483647,'__ladli_rollback_test__',repeat('a',64),CURRENT_TIMESTAMP::text,1);
INSERT INTO public.admin_sessions(token_hash,admin_user_id,password_fingerprint,csrf_token,expires_at)
  VALUES(repeat('b',64),-2147483647,'test-fingerprint','test-csrf',CURRENT_TIMESTAMP+INTERVAL '30 minutes');

DO $$
BEGIN
  IF NOT public.ladli_admit(repeat('c',64),1,60) THEN RAISE EXCEPTION 'First admission failed'; END IF;
  IF public.ladli_admit(repeat('c',64),1,60) THEN RAISE EXCEPTION 'Rate limit was not enforced'; END IF;
  IF public.ladli_change_password(-2147483647,'stale-hash',repeat('d',64)) THEN
    RAISE EXCEPTION 'Stale password change was accepted';
  END IF;
  IF NOT public.ladli_change_password(-2147483647,repeat('a',64),repeat('d',64)) THEN
    RAISE EXCEPTION 'Valid password compare-and-swap failed';
  END IF;
  IF EXISTS(SELECT 1 FROM public.admin_sessions WHERE admin_user_id=-2147483647) THEN
    RAISE EXCEPTION 'Password change did not revoke sessions';
  END IF;
  IF NOT public.ladli_set_questions(-2147483647,repeat('d',64),jsonb_build_array(
    jsonb_build_object('question_id',1,'answer_hash',repeat('e',64)),
    jsonb_build_object('question_id',2,'answer_hash',repeat('e',64)),
    jsonb_build_object('question_id',3,'answer_hash',repeat('e',64))),true) THEN
    RAISE EXCEPTION 'Question setup failed';
  END IF;
  BEGIN
    PERFORM public.ladli_set_questions(-2147483647,repeat('d',64),jsonb_build_array(
      jsonb_build_object('question_id',1,'answer_hash',repeat('f',64)),
      jsonb_build_object('question_id',2,'answer_hash',repeat('f',64)),
      jsonb_build_object('question_id',2147483647,'answer_hash',repeat('f',64))),false);
    RAISE EXCEPTION 'Invalid question reference was accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  IF (SELECT count(*) FROM public.admin_security_answers
      WHERE admin_user_id=-2147483647 AND answer_hash=repeat('e',64)) <> 3 THEN
    RAISE EXCEPTION 'Failed question replacement was not atomic';
  END IF;
END;
$$;
SELECT 'rate limiting, stale-change rejection, session revocation and atomic question replacement passed' AS verification;
ROLLBACK;
