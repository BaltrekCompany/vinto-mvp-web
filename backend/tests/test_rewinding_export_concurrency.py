"""RBE-04: isolated PostgreSQL 17 concurrency gate for the actual active-reservation index.

ONLY runs against disposable *_test DB. session_replication_role=replica is used to
seed synthetic, non-operational FK identifiers without copying production records.
This tests index serialization, not the end-to-end service or its triggers.
"""
import concurrent.futures
import threading
import unittest
from uuid import uuid4

from app.db_guard import connect_test_database


class ReservationConcurrencyTests(unittest.TestCase):
    def test_two_operators_cannot_reserve_same_child_concurrently(self):
        child_id = uuid4()
        gate = threading.Barrier(2)

        def attempt():
            with connect_test_database(connect_timeout=4) as connection:
                connection.autocommit = True
                # CI runs as the owner of a completely disposable PG17 database.
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role = replica")
                    gate.wait(timeout=8)
                    row = connection.execute(
                        """INSERT INTO vinto_txn.rewinding_export_reservation
                           (report_id, package_id, package_child_id, child_bobbin_id, reserved_by)
                           VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING RETURNING id""",
                        (uuid4(), uuid4(), uuid4(), child_id, uuid4()),
                    ).fetchone()
                    return row is not None

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                tasks = [pool.submit(attempt) for _ in range(2)]
                outcome = [task.result(timeout=18) for task in tasks]
            self.assertEqual(sorted(outcome), [False, True])
            with connect_test_database(connect_timeout=4) as connection:
                live = connection.execute(
                    """SELECT count(*) FROM vinto_txn.rewinding_export_reservation
                       WHERE child_bobbin_id=%s AND released_at IS NULL""",
                    (child_id,),
                ).fetchone()[0]
                self.assertEqual(live, 1)
        finally:
            # Delete only this synthetic child's rows; bypass immutable-history
            # triggers solely inside the disposable test database.
            with connect_test_database(connect_timeout=4) as connection:
                connection.execute("SET LOCAL session_replication_role = replica")
                connection.execute(
                    "DELETE FROM vinto_txn.rewinding_export_reservation WHERE child_bobbin_id=%s",
                    (child_id,),
                )
                connection.commit()

    def test_report_package_child_fk_and_active_index_exist(self):
        with connect_test_database(connect_timeout=4) as connection:
            constraints = connection.execute(
                """SELECT conname FROM pg_constraint
                   WHERE conrelid='vinto_txn.rewinding_export_reservation'::regclass""",
            ).fetchall()
            names = {row[0] for row in constraints}
            self.assertIn("rewinding_export_reservation_package_child_fk", names)
            self.assertIn("rewinding_export_reservation_bobbin_selection_fk", names)
            active_index = connection.execute(
                """SELECT indexdef FROM pg_indexes WHERE schemaname='vinto_txn'
                   AND indexname='rewinding_export_reservation_active_bobbin_uidx'""",
            ).fetchone()
            self.assertIsNotNone(active_index)
            self.assertIn("UNIQUE INDEX", active_index[0])
            self.assertIn("released_at IS NULL", active_index[0])


if __name__ == "__main__":
    unittest.main()
