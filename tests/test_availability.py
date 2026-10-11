import unittest
from unittest.mock import Mock, patch

import db

# Startup must never connect to the database, even when it is unreachable.
with patch.object(db, "init_db", side_effect=RuntimeError("database offline")) as bootstrap:
    import app as website
    assert bootstrap.call_count == 0, "Application startup tried to initialise the database"


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        website._db_ready = False
        website._db_retry_at = 0
        self.client = website.app.test_client()

    def test_public_pages_and_assets_never_initialise_database(self):
        with patch.object(db, "init_db", side_effect=RuntimeError("offline")) as init:
            for path in ("/", "/about.html", "/contact.html", "/healthz"):
                with self.subTest(path=path):
                    with self.client.get(path) as response:
                        self.assertEqual(response.status_code, 200)
            from pathlib import Path
            asset = next(Path(website.SITE_DIR, "assets").rglob("*.css"))
            with self.client.get("/" + asset.relative_to(website.SITE_DIR).as_posix()) as response:
                self.assertEqual(response.status_code, 200)
            init.assert_not_called()

    def test_database_requests_fail_honestly_and_back_off(self):
        with patch.object(db, "init_db", side_effect=RuntimeError("offline")) as init:
            with patch.object(db, "get_db") as connection:
                for path in ("/api/contact", "/api/quote", "/api/admin/login"):
                    response = self.client.post(path, json={})
                    self.assertEqual(response.status_code, 503)
                    self.assertFalse(response.json["ok"])
                    self.assertEqual(response.headers["Retry-After"], "30")
                self.assertEqual(self.client.get("/health").status_code, 503)
                self.assertEqual(self.client.get("/healthz").status_code, 200)
                with self.client.get("/") as response:
                    self.assertEqual(response.status_code, 200)
                init.assert_called_once()
                connection.assert_not_called()

    def test_bootstrap_recovers_after_backoff(self):
        with patch.object(website.time, "monotonic", return_value=100):
            with patch.object(db, "init_db", side_effect=RuntimeError("offline")):
                self.assertFalse(website.ensure_db_ready())
        with patch.object(website.time, "monotonic", return_value=131):
            with patch.object(db, "init_db") as init:
                self.assertTrue(website.ensure_db_ready())
                self.assertTrue(website.ensure_db_ready())
                init.assert_called_once()

    def test_health_closes_connection_when_query_fails(self):
        website._db_ready = True
        connection = Mock()
        connection.execute.side_effect = RuntimeError("connection lost")
        with patch.object(db, "get_db", return_value=connection):
            self.assertEqual(self.client.get("/health").status_code, 503)
            connection.close.assert_called_once()

    def test_health_confirms_database_and_schema(self):
        with patch.object(db, "init_db"), patch.object(db, "get_db", return_value=Mock()):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["schema"], "ready")

    def test_database_drivers_receive_connection_timeout(self):
        with patch.dict(db.os.environ, {"PGCONNECT_TIMEOUT": "4"}):
            params = db.get_pg_connection_params()
            self.assertEqual(params["connect_timeout"], 4)
        with patch.object(db, "pg8000_dbapi", Mock(), create=True) as driver:
            db._pg8000_connect(params)
            self.assertEqual(driver.connect.call_args.kwargs["timeout"], 4)

    def test_pool_supports_gunicorn_threads(self):
        old_pool = db._pg_pool
        db._pg_pool = None
        try:
            with patch.object(db, "PG_DRIVER", "psycopg2"), patch.object(db, "is_postgres_configured", return_value=True):
                with patch.object(db, "pool", Mock(), create=True) as pools:
                    self.assertIs(db._get_pg_pool(), pools.ThreadedConnectionPool.return_value)
                    db._get_pg_pool()
                    pools.ThreadedConnectionPool.assert_called_once()
        finally:
            db._pg_pool = old_pool


if __name__ == "__main__":
    unittest.main()
