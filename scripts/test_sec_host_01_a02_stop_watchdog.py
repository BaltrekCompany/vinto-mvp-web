"""SEC-HOST-01 A0.2: unit tests without Docker, PostgreSQL or host changes."""
import importlib.util
import json
import stat
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).with_name("sec-host-01-a02-stop-watchdog.py")
SPEC = importlib.util.spec_from_file_location("sec_a02_watchdog", PATH)
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = watchdog
SPEC.loader.exec_module(watchdog)

def baseline(**overrides):
    x = dict(
        container_id="a" * 64,
        db="targetdb",
        role="readeradmin",
        baseline_source="default",
        baseline_verified=True,
        armed_epoch=1_800_000_000,
        deadline_epoch=1_800_000_360,
        log_bytes_at_arm=1_000,
        max_log_growth_bytes=50_000,
        min_free_bytes=10_000,
        phase="observing",
    )
    x.update(overrides)
    return x

class StateTests(unittest.TestCase):
    def test_exact_private_state_and_no_auto_override(self):
        good = watchdog.Observation.from_mapping(baseline())
        self.assertEqual(good.baseline_source, "default")
        bad = [
            {"container_id": "a" * 63},
            {"baseline_verified": False},
            {"baseline_source": "auto"},
            {"baseline_source": "mystery"},
            {"db": "targetdb;DROP"},
            {"role": "role name"},
            {"phase": "started_unknown"},
            {"deadline_epoch": 1_800_000_000},
            {"deadline_epoch": 1_800_700_000},
            {"armed_epoch": "not-a-number"},
            {"max_log_growth_bytes": 0},
            {"max_log_growth_bytes": 200 * 1024 * 1024},
            {"min_free_bytes": 0},
        ]
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(watchdog.Blocked):
                    watchdog.Observation.from_mapping(baseline(**change))
        with self.assertRaises(watchdog.Blocked):
            watchdog.Observation.from_mapping({**baseline(), "unknown": "x"})

    def test_file_owner_and_mode_verified_before_host_execution(self):
        bad_file = SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_uid=0)
        good_dir = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        with mock.patch.object(watchdog.Path, "lstat", return_value=bad_file), \
             mock.patch.object(watchdog.Path, "stat", return_value=good_dir):
            with self.assertRaisesRegex(watchdog.Blocked, "EXECUTABLE_INTEGRITY"):
                watchdog.validate_executable()
        good_file = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)
        with mock.patch.object(watchdog.Path, "lstat", return_value=good_file), \
             mock.patch.object(watchdog.Path, "stat", return_value=good_dir):
            watchdog.validate_executable()
        nonroot_file = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=1001)
        with mock.patch.object(watchdog.Path, "lstat", return_value=nonroot_file), \
             mock.patch.object(watchdog.Path, "stat", return_value=good_dir):
            with self.assertRaisesRegex(watchdog.Blocked, "EXECUTABLE_INTEGRITY"):
                watchdog.validate_executable()

    def test_deadline_oversize_or_low_disk_always_triggers_stop(self):
        obs = watchdog.Observation.from_mapping(baseline())
        self.assertEqual(watchdog.decide(obs, 1_800_000_200, 1400, 10_000), "WAIT")
        for kwargs in [
            (1_800_000_360, 1400, 10_000),
            (1_800_000_100, 51_000, 10_000),
            (1_800_000_100, 1400, 9999),
            (1_799_999_999, 1400, 10_000),
            (1_800_000_100, 999, 10_000),
        ]:
            self.assertEqual(watchdog.decide(obs, *kwargs), "STOP")
        self.assertEqual(
            watchdog.decide(watchdog.Observation.from_mapping(baseline(phase="stopping")),
                            1_800_000_100, 1400, 10_000), "STOP"
        )
        self.assertEqual(
            watchdog.decide(watchdog.Observation.from_mapping(baseline(phase="restored")),
                            1_800_000_999, 1400, 10_000), "DONE"
        )

class FakeController:
    sizes = (1200, 20000)
    restore_result = "RESTORED"
    restore_calls = 0
    def __init__(self, obs):
        self.obs = obs
    def inspect(self):
        return self.sizes
    def restore(self):
        self.__class__.restore_calls += 1
        return self.restore_result

class TickTests(unittest.TestCase):
    def setUp(self):
        FakeController.sizes = (1200, 20000)
        FakeController.restore_result = "RESTORED"
        FakeController.restore_calls = 0
        self.saved = []
        self.patch_read = mock.patch.object(watchdog, "read_state",
                             return_value=watchdog.Observation.from_mapping(baseline()))
        self.patch_save = mock.patch.object(watchdog, "save_state",
                             side_effect=self.saved.append)
        self.patch_read.start()
        self.patch_save.start()
        self.addCleanup(self.patch_read.stop)
        self.addCleanup(self.patch_save.stop)

    def test_before_deadline_does_not_write_or_call_restore(self):
        result = watchdog.tick(clock=1_800_000_100, controller_factory=FakeController)
        self.assertEqual(result, "ARMED_MONITORING")
        self.assertEqual(FakeController.restore_calls, 0)
        self.assertEqual(self.saved, [])

    def test_deadline_restores_and_persists_success(self):
        result = watchdog.tick(clock=1_800_000_999, controller_factory=FakeController)
        self.assertEqual(result, "RESTORED_AND_VERIFIED")
        self.assertEqual(FakeController.restore_calls, 1)
        self.assertEqual([state.phase for state in self.saved], ["stopping", "restored"])

    def test_emergency_off_does_not_claim_exact_restore(self):
        FakeController.restore_result = "OFF_REQUIRES_SOURCE_RESTORE"
        with self.assertRaisesRegex(watchdog.Blocked, "OFF_BUT_SOURCE_RESTORE_REQUIRED"):
            watchdog.tick(clock=1_800_000_999, controller_factory=FakeController)
        self.assertEqual([state.phase for state in self.saved], ["stopping"])

    def test_failed_postgres_stays_stopping_for_future_retries(self):
        FakeController.restore_result = "STOP_RETRY_REQUIRED"
        with self.assertRaisesRegex(watchdog.Blocked, "STOP_RETRY_REQUIRED"):
            watchdog.tick(clock=1_800_000_999, controller_factory=FakeController)
        self.assertEqual([state.phase for state in self.saved], ["stopping"])

class PgControllerTests(unittest.TestCase):
    def setUp(self):
        self.obs = watchdog.Observation.from_mapping(baseline())
        self.pg = watchdog.PgController(self.obs)

    def test_reset_and_reload_are_separate_commands_and_verify_in_fresh_session(self):
        calls = []
        def fake(sql, readonly):
            calls.append((sql, readonly))
            if sql == "SELECT pg_reload_conf();":
                return "t"
            if "setting ||" in sql:
                return "off|default|false"
            return ""
        with mock.patch.object(self.pg, "_psql", side_effect=fake):
            self.assertEqual(self.pg.restore(), "RESTORED")
        self.assertEqual(calls[0], ("ALTER SYSTEM RESET log_connections;", False))
        self.assertEqual(calls[1], ("SELECT pg_reload_conf();", False))
        self.assertTrue(calls[2][1])
        self.assertEqual(len(calls), 3)

    def test_failed_reset_attempts_set_off_but_never_claims_full_restore(self):
        commands = []
        def fake(sql, readonly):
            commands.append(sql)
            if sql == "ALTER SYSTEM RESET log_connections;":
                raise watchdog.Blocked("mock-error")
            if sql == "SELECT pg_reload_conf();":
                return "t"
            if "setting ||" in sql:
                return "off|configuration file|false"
            return ""
        with mock.patch.object(self.pg, "_psql", side_effect=fake):
            self.assertEqual(self.pg.restore(), "OFF_REQUIRES_SOURCE_RESTORE")
        self.assertIn("ALTER SYSTEM SET log_connections = off;", commands)

    def test_no_success_when_reload_or_state_check_fails(self):
        with mock.patch.object(self.pg, "_psql", side_effect=watchdog.Blocked("fail")):
            self.assertEqual(self.pg.restore(), "STOP_RETRY_REQUIRED")

    def test_psql_commands_use_pinned_container_identifier(self):
        commands = []
        def fake_run(cmd, timeout=20):
            commands.append(cmd)
            return "off|default|false"
        with mock.patch.object(self.pg, "_run", side_effect=fake_run):
            self.pg.state()
        self.assertEqual(commands[0][0:2], ["docker", "exec"])
        self.assertEqual(commands[0][4], self.obs.container_id)
        self.assertIn("default_transaction_read_only=on", commands[0][3])
        self.assertNotIn("ALTER SYSTEM", " ".join(commands[0]))

class StaticContractTests(unittest.TestCase):
    def test_no_start_mode_or_public_endpoint_identifiers(self):
        text = PATH.read_text(encoding="utf8")
        self.assertNotIn("ALTER SYSTEM SET log_connections = on", text)
        self.assertNotIn("ALTER SYSTEM SET log_connections = true", text)
        self.assertNotIn("docker run", text)
        self.assertNotIn("docker restart", text)
        self.assertNotIn("PGPASSWORD", text)
        self.assertNotIn("postgresql://", text)
        self.assertIn("SEC_HOST_A02_WATCHDOG=BLOCKED_", text)

if __name__ == "__main__":
    unittest.main()
