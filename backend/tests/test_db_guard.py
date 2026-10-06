"""La protección debe rechazar bases que no sean *_test antes de cualquier mutación."""

import unittest
from unittest.mock import MagicMock, patch

from psycopg.conninfo import make_conninfo

from app.config import settings
from app.db_guard import (UnsafeDatabaseError, assert_test_database, connect_test_database,
                          is_test_database_name)


def fake_connection(database_name):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (database_name,)
    return connection


class DatabaseNameRuleTests(unittest.TestCase):
    def test_only_names_ending_in_test_are_accepted(self):
        self.assertTrue(is_test_database_name("vinto_test"))
        for name in ("vinto", "vinto_test_backup", "test", "_test", "", "vinto_prod"):
            self.assertFalse(is_test_database_name(name), name)

    def test_guard_accepts_test_name_and_asks_postgres_for_it(self):
        connection = fake_connection("vinto_test")
        self.assertEqual(assert_test_database(connection), "vinto_test")
        connection.execute.assert_called_once_with("SELECT current_database()")

    def test_guard_rejects_dev_name_after_a_single_select(self):
        connection = fake_connection("vinto")
        with self.assertRaisesRegex(UnsafeDatabaseError, "No se ejecut"):
            assert_test_database(connection)
        connection.execute.assert_called_once_with("SELECT current_database()")


class RealConnectionTests(unittest.TestCase):
    def test_configured_test_database_is_vinto_test(self):
        connection = connect_test_database(connect_timeout=3)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT current_database()").fetchone()[0], "vinto_test")

    def test_dev_database_is_rejected(self):
        self.assertIsNotNone(settings.database_url, "DATABASE_URL requerida para esta prueba")
        with self.assertRaises(UnsafeDatabaseError):
            connect_test_database(settings.database_url.get_secret_value(), connect_timeout=3)

    def test_name_inside_connection_string_is_not_trusted(self):
        # La cadena "dice" _test, pero PostgreSQL responde con la base real.
        disguised = make_conninfo(settings.database_url.get_secret_value(), application_name="vinto_test")
        with self.assertRaises(UnsafeDatabaseError):
            connect_test_database(disguised, connect_timeout=3)

    def test_missing_test_url_is_an_error_not_a_fallback(self):
        with patch.object(settings, "test_database_url", None):
            with self.assertRaisesRegex(UnsafeDatabaseError, "TEST_DATABASE_URL"):
                connect_test_database()


if __name__ == "__main__":
    unittest.main()
