"""Destructive integration tests: TEST_DATABASE_URL MUST name a disposable DB."""
import concurrent.futures
import os
import threading
import unittest
from unittest.mock import patch

import db
from werkzeug.security import check_password_hash


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable TEST_DATABASE_URL')
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = patch.object(db, 'DATABASE_URL', os.environ['TEST_DATABASE_URL'])
        cls.config.start()
        cls.old_pool = db._pg_pool
        db._pg_pool = None
        db.init_db(default_password='Initial-test-password-123')

    @classmethod
    def tearDownClass(cls):
        if db._pg_pool:
            db._pg_pool.closeall()
        db._pg_pool = cls.old_pool
        cls.config.stop()

    def setUp(self):
        with db.get_db() as conn:
            conn.execute('TRUNCATE admin_users, admin_security_answers, password_history, password_reset_tokens, login_attempts, recovery_attempts, request_rate_limits, inquiries RESTART IDENTITY CASCADE')
        db.init_db(default_password='Initial-test-password-123')

    def test_concurrent_bootstrap_is_idempotent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda _: db.init_db(default_password='Initial-test-password-123'), range(3)))
        with db.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS c FROM admin_users').fetchone()['c'], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) AS c FROM schema_migrations').fetchone()['c'], 2)
            self.assertEqual(conn.execute('SELECT must_change_password FROM admin_users').fetchone()['must_change_password'], 1)

    def test_reset_token_allows_exactly_one_concurrent_success(self):
        token = db.create_reset_token('admin')
        barrier = threading.Barrier(2)
        def reset(i):
            barrier.wait()
            return db.reset_password_with_token(token, f'Concurrent-password-{i}-123')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reset, range(2)))
        self.assertEqual(results.count('admin'), 1)
        self.assertEqual(results.count(None), 1)
        self.assertIsNone(db.reset_password_with_token(token, 'Replay-password-123'))

    def test_failed_password_update_rolls_back_token_consumption(self):
        token = db.create_reset_token('admin')
        with self.assertRaises(ValueError):
            db.reset_password_with_token(token, 'Initial-test-password-123')
        self.assertEqual(db.reset_password_with_token(token, 'New-test-password-123'), 'admin')

    def test_expired_token_and_other_tokens_are_invalidated(self):
        token = db.create_reset_token('admin')
        with db.get_db() as conn:
            conn.execute("UPDATE password_reset_tokens SET expires_at = '2000-01-01T00:00:00'")
        self.assertIsNone(db.reset_password_with_token(token, 'New-test-password-123'))
        other = db.create_reset_token('admin')
        db.set_password('admin', 'Changed-test-password-123')
        self.assertIsNone(db.reset_password_with_token(other, 'Another-test-password-123'))

    def test_old_password_history_and_stale_change_are_rejected(self):
        original = db.find_admin_by_username_or_email('admin')['password_hash']
        db.set_password('admin', 'Changed-test-password-123', expected_hash=original)
        with self.assertRaises(ValueError):
            db.set_password('admin', 'Third-test-password-123', expected_hash=original)
        with self.assertRaises(ValueError):
            db.set_password('admin', 'Initial-test-password-123')
        self.assertTrue(check_password_hash(db.find_admin_by_username_or_email('admin')['password_hash'], 'Changed-test-password-123'))

    def test_shared_rate_limit_is_atomic_under_concurrency(self):
        barrier = threading.Barrier(4)
        def admit(_):
            barrier.wait()
            return db.admit_request('shared-test-bucket', 2, 60)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(admit, range(4)))
        self.assertEqual(results.count(True), 2)
        self.assertEqual(results.count(False), 2)

    def test_sql_error_does_not_poison_next_connection(self):
        with self.assertRaises(Exception):
            with db.get_db() as conn:
                conn.execute('SELECT 1 / 0')
        with db.get_db() as conn:
            self.assertEqual(conn.execute('SELECT 1 AS ok').fetchone()['ok'], 1)

    def test_security_answer_replacement_rolls_back_on_invalid_question(self):
        from werkzeug.security import generate_password_hash
        questions = db.get_security_questions()[:3]
        answers = [{'question_id': q['id'], 'answer_hash': generate_password_hash('test-answer')} for q in questions]
        admin = db.find_admin_by_username_or_email('admin')
        db.save_security_answers(admin['id'], answers)
        answers[2]['question_id'] = 999999
        with self.assertRaises(Exception):
            db.save_security_answers(admin['id'], answers)
        self.assertEqual(len(db.get_user_security_questions(admin['id'])), 3)

    def test_enquiry_admin_password_change_and_logout_end_to_end(self):
        import app as website
        with patch.object(website, '_db_ready', True):
            client = website.app.test_client()
            response = client.post('/api/contact', json={'name': 'Test customer', 'email': 'test@example.com', 'message': 'Test enquiry'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/api/admin/inquiries').status_code, 401)
            response = client.post('/api/admin/login', json={'username': 'admin', 'password': 'Initial-test-password-123'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['must_change_password'])
            self.assertEqual(client.get('/api/admin/inquiries').status_code, 403)
            token = client.get('/api/admin/csrf-token').json['csrf_token']
            self.assertEqual(client.get('/api/admin/csrf-token').json['csrf_token'], token)
            response = client.post('/api/admin/change-password', json={'current_password': 'Initial-test-password-123', 'new_password': 'Changed-test-password-123'}, headers={'X-CSRF-Token': token})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(client.get('/api/admin/me').json['logged_in'])
            self.assertEqual(client.post('/api/admin/login', json={'username': 'admin', 'password': 'Changed-test-password-123'}).status_code, 200)
            rows = client.get('/api/admin/inquiries').json
            self.assertEqual(rows[0]['message'], 'Test enquiry')
            token = client.get('/api/admin/csrf-token').json['csrf_token']
            headers = {'X-CSRF-Token': token}
            self.assertEqual(client.post(f"/api/admin/inquiries/{rows[0]['id']}/status", json={'status': 'closed'}, headers=headers).status_code, 200)
            self.assertEqual(client.post('/api/admin/logout', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/admin/inquiries').status_code, 401)


if __name__ == '__main__':
    unittest.main()
