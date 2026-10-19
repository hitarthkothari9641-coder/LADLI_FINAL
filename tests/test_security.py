import io
import os
import runpy
import unittest
from unittest.mock import Mock, patch

from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash
import app as website
import db


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-only-password-123')

    def setUp(self):
        self.ready = patch.object(website, 'ensure_db_ready', return_value=True)
        self.ready.start()
        self.addCleanup(self.ready.stop)
        self.client = website.app.test_client()
        self.conn = Mock()
        self.conn.execute.return_value.fetchone.return_value = {
            'password_hash': self.password_hash, 'must_change_password': 0,
        }

    def login(self, fingerprint=None):
        with self.client.session_transaction() as session:
            session['admin_user'] = 'admin'
            session['pw_fp'] = fingerprint or website._password_fingerprint(self.password_hash)
            session['csrf_token'] = 'test-csrf-token'

    def test_every_decorated_admin_route_requires_authentication(self):
        for rule in website.app.url_map.iter_rules():
            view = website.app.view_functions[rule.endpoint]
            if not hasattr(view, '__wrapped__'):
                continue
            path = rule.rule.replace('<int:inquiry_id>', '1')
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.client.open(path, method=method, json={}).status_code, 401)

    def test_every_admin_mutation_requires_csrf(self):
        self.login()
        for rule in website.app.url_map.iter_rules():
            if not hasattr(website.app.view_functions[rule.endpoint], '__wrapped__'):
                continue
            path = rule.rule.replace('<int:inquiry_id>', '1')
            for method in rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}:
                for token in (None, 'wrong'):
                    with self.subTest(path=path, token=token):
                        headers = {'X-CSRF-Token': token} if token else {}
                        self.assertEqual(self.client.open(path, method=method, headers=headers, json={}).status_code, 403)

    def test_expired_fingerprint_and_removed_account_are_rejected(self):
        self.login('obsolete')
        with patch.object(db, 'get_db', return_value=self.conn):
            self.assertEqual(self.client.get('/api/admin/inquiries').status_code, 401)
        self.login()
        self.conn.execute.return_value.fetchone.return_value = None
        with patch.object(db, 'get_db', return_value=self.conn):
            self.assertEqual(self.client.get('/api/admin/inquiries').status_code, 401)

    def test_logout_requires_valid_csrf_and_clears_session(self):
        self.login()
        with patch.object(db, 'get_db', return_value=self.conn):
            response = self.client.post('/api/admin/logout', headers={'X-CSRF-Token': 'test-csrf-token'})
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn('admin_user', session)

    def test_recovery_is_owner_controlled_by_default(self):
        with patch.dict(os.environ, {'ALLOW_SECURITY_QUESTION_RECOVERY': 'false'}):
            for path in ('get-user-questions', 'verify-security-answers', 'reset-password-with-token'):
                self.assertEqual(self.client.post('/api/admin/' + path, json={}).status_code, 403)
            with self.client.get('/admin/forgot-password') as response:
                self.assertIn(b'Contact the site owner', response.data)

    def test_forwarded_headers_require_trusted_peer_and_complete_chain(self):
        cases = [
            ('198.51.100.20', '1', '203.0.113.9', '198.51.100.20'),
            ('127.0.0.1', '0', '203.0.113.9', '127.0.0.1'),
            ('127.0.0.1', '1', 'spoofed, 203.0.113.9', '203.0.113.9'),
            ('127.0.0.1', '2', '203.0.113.9', '127.0.0.1'),
            ('127.0.0.1', '1', 'bad-ip', '127.0.0.1'),
        ]
        for peer, count, forwarded, expected in cases:
            with self.subTest(peer=peer, count=count, forwarded=forwarded):
                with patch.dict(os.environ, {'TRUSTED_PROXY_COUNT': count, 'TRUSTED_PROXY_CIDRS': '127.0.0.1/32'}):
                    with website.app.test_request_context('/', environ_base={'REMOTE_ADDR': peer}, headers={'X-Forwarded-For': forwarded}):
                        self.assertEqual(website._client_ip(), expected)

    def test_gunicorn_does_not_trust_all_proxies(self):
        with patch.dict(os.environ, {}, clear=True):
            config = runpy.run_path('gunicorn.conf.py')
        self.assertNotIn('*', config['forwarded_allow_ips'])
        self.assertEqual(config['workers'], 2)
        self.assertNotIn('%(r)', config['access_log_format'])

    def test_upload_validation_and_production_storage_requirement(self):
        for name, data, mime in [('a.txt', b'%PDF-1.7', 'application/pdf'),
                                 ('a.pdf', b'fake', 'application/pdf'),
                                 ('a.pdf', b'%PDF-1.7', 'text/html'),
                                 ('a.pdf', b'%PDF-' + b'x' * (3 * 1024 * 1024), 'application/pdf')]:
            with self.subTest(name=name, mime=mime):
                with self.assertRaises(ValueError):
                    website._save_quote_attachment(FileStorage(io.BytesIO(data), filename=name, content_type=mime))
        with patch.dict(website.app.config, {'SESSION_COOKIE_SECURE': True}), patch.object(website, '_get_s3_client', return_value=None):
            with self.assertRaises(RuntimeError):
                website._save_quote_attachment(FileStorage(io.BytesIO(b'%PDF-1.7'), filename='a.pdf', content_type='application/pdf'))

    def test_upload_uses_generated_key_and_encryption(self):
        s3 = Mock()
        with patch.object(website, '_get_s3_client', return_value=s3):
            key, name, size = website._save_quote_attachment(FileStorage(io.BytesIO(b'%PDF-1.7'), filename='../../invoice.pdf', content_type='application/pdf'))
        self.assertRegex(key, r'^attachments/[a-f0-9]{32}\.pdf$')
        self.assertEqual(name, 'invoice.pdf')
        self.assertEqual(s3.upload_fileobj.call_args.kwargs['ExtraArgs']['ServerSideEncryption'], 'AES256')

    def test_failed_storage_does_not_create_successful_enquiry(self):
        with patch.object(website._rate_limiter, 'is_limited', return_value=False), patch.object(website, '_save_quote_attachment', side_effect=RuntimeError('offline')), patch.object(db, 'get_db') as connect:
            response = self.client.post('/api/quote', data={'contact_name': 'Test', 'email': 'test@example.com', 'attachment': (io.BytesIO(b'%PDF-1.7'), 'a.pdf')})
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['ok'])
            connect.assert_not_called()

    def test_duplicate_correct_answer_cannot_replace_three_answers(self):
        self.conn.execute.return_value.fetchall.return_value = [{'question_id': i, 'answer_hash': self.password_hash} for i in (1, 2, 3)]
        with patch.object(db, 'get_db', return_value=self.conn):
            self.assertFalse(db.verify_security_answers(1, [{'question_id': 1, 'answer': 'test-only-password-123'}] * 3))
            self.assertFalse(db.verify_security_answers(1, ['bad', 'shape', 'data']))
            self.assertTrue(db.verify_security_answers(1, [{'question_id': i, 'answer': 'test-only-password-123'} for i in (1, 2, 3)]))

    def test_connection_is_closed_when_database_function_raises(self):
        self.conn.execute.side_effect = RuntimeError('query failed')
        with patch.object(db, 'get_db', return_value=self.conn):
            with self.assertRaises(RuntimeError):
                db.find_admin_by_username_or_email('admin')
        self.conn.close.assert_called_once()

    def test_commit_failure_still_rolls_back_and_releases_pool_connection(self):
        raw = Mock()
        raw.commit.side_effect = RuntimeError('commit failed')
        pool = Mock()
        with patch.object(db, '_pg_pool', pool):
            with self.assertRaises(RuntimeError):
                with db.PostgresConnectionWrapper(raw, from_pool=True):
                    pass
        raw.rollback.assert_called_once()
        pool.putconn.assert_called_once_with(raw, close=False)

    def test_broken_connection_is_discarded(self):
        raw = Mock()
        raw.rollback.side_effect = RuntimeError('socket closed')
        pool = Mock()
        with patch.object(db, '_pg_pool', pool):
            conn = db.PostgresConnectionWrapper(raw, from_pool=True)
            conn.close()
            conn.close()
        pool.putconn.assert_called_once_with(raw, close=True)

    def test_legacy_and_aware_password_history_dates(self):
        for date in ('2020-01-01T00:00:00', '2020-01-01T00:00:00+00:00'):
            self.assertIn('days ago', db._humanize_delta(date))

    def test_admin_responses_are_not_cacheable(self):
        with self.client.get('/admin/login') as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_untrusted_host_and_malformed_json_are_rejected(self):
        self.assertEqual(self.client.get('/', headers={'Host': 'attacker.invalid'}).status_code, 400)
        for body in ([], {'username': []}, {'email': 123}):
            self.assertEqual(self.client.post('/api/admin/login', json=body).status_code, 400)


if __name__ == '__main__':
    unittest.main()
