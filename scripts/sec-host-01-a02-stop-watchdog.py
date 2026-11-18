#!/usr/bin/env python3
"""SEC-HOST-01 A0.2: stop-only watchdog for a future approved PG observation.

No START, no logging enablement, no networking/firewall changes. Do not
install in any host without separate authorization and a private root-owned
state generated from an independently verified preflight.
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

STATE_DIR = Path("/var/lib/sec-a01-watchdog")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "tick.lock"
MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60
MAX_LOG_GROWTH_BYTES = 100 * 1024 * 1024
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
PHASES = frozenset(("armed", "observing", "stopping", "restored"))


class Blocked(RuntimeError):
    """Fail closed without displaying operational identifiers or secrets."""


@dataclass(frozen=True)
class Observation:
    container_id: str
    db: str
    role: str
    baseline_source: str
    baseline_verified: bool
    armed_epoch: int
    deadline_epoch: int
    log_bytes_at_arm: int
    max_log_growth_bytes: int
    min_free_bytes: int
    phase: str

    @classmethod
    def from_mapping(cls, value: dict) -> "Observation":
        fields = frozenset(cls.__dataclass_fields__)
        if not isinstance(value, dict) or frozenset(value) != fields:
            raise Blocked("STATE_SCHEMA_CHANGED")
        for key in (
            "armed_epoch", "deadline_epoch", "log_bytes_at_arm",
            "max_log_growth_bytes", "min_free_bytes",
        ):
            if type(value[key]) is not int:
                raise Blocked("INVALID_INTEGER_FIELD")
        if type(value["baseline_verified"]) is not bool or not value["baseline_verified"]:
            raise Blocked("ORIGINAL_SOURCE_NOT_VERIFIED")
        if not CONTAINER_ID_RE.fullmatch(value["container_id"]):
            raise Blocked("INVALID_CONTAINER_ID")
        if not IDENTIFIER_RE.fullmatch(value["db"]) or not IDENTIFIER_RE.fullmatch(value["role"]):
            raise Blocked("INVALID_PG_TARGET")
        if value["baseline_source"] not in ("default", "regular"):
            # A pre-existing auto.conf entry needs a different exact restore
            # plan. This watchdog deliberately refuses that scenario.
            raise Blocked("UNSUPPORTED_RESTORE_SOURCE")
        if value["phase"] not in PHASES:
            raise Blocked("UNKNOWN_STATE")
        if value["armed_epoch"] <= 0 or value["deadline_epoch"] <= value["armed_epoch"]:
            raise Blocked("INVALID_DEADLINE")
        if value["deadline_epoch"] - value["armed_epoch"] > MAX_WINDOW_SECONDS:
            raise Blocked("WINDOW_EXCEEDS_SAFETY_LIMIT")
        if not 0 <= value["log_bytes_at_arm"] <= 2**63 - 1:
            raise Blocked("INVALID_LOG_BASELINE")
        if not 1 <= value["max_log_growth_bytes"] <= MAX_LOG_GROWTH_BYTES:
            raise Blocked("INVALID_LOG_CAP")
        if not 1 <= value["min_free_bytes"] <= 100 * 1024**3:
            raise Blocked("INVALID_DISK_FLOOR")
        return cls(**value)

    def as_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


def decide(obs: Observation, now: int, log_bytes: int, free_bytes: int) -> str:
    """Pure decision for each tick, no Docker or DB access."""
    if obs.phase == "restored":
        return "DONE"
    if obs.phase == "stopping":
        return "STOP"
    if now < obs.armed_epoch or now < 1_600_000_000:
        return "STOP"  # suspicious clock: prioritize stopping
    if now >= obs.deadline_epoch:
        return "STOP"
    if log_bytes < obs.log_bytes_at_arm:
        return "STOP"  # unexpected truncation/rotation, do not trust cap
    if log_bytes - obs.log_bytes_at_arm >= obs.max_log_growth_bytes:
        return "STOP"
    if free_bytes < obs.min_free_bytes:
        return "STOP"
    return "WAIT"


def validate_dir() -> None:
    if STATE_DIR.is_symlink() or not STATE_DIR.is_dir():
        raise Blocked("PRIVATE_STATE_DIR_MISSING")
    st = STATE_DIR.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        raise Blocked("PRIVATE_STATE_DIR_PERMISSIONS")


def read_state() -> Observation:
    validate_dir()
    try:
        fd = os.open(STATE_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise Blocked("STATE_FILE_NOT_AVAILABLE") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise Blocked("PRIVATE_STATE_FILE_PERMISSIONS")
        if info.st_size > 4096:
            raise Blocked("STATE_TOO_LARGE")
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            fd = -1
            value = json.load(source)
    except (ValueError, UnicodeError) as exc:
        raise Blocked("INVALID_STATE_JSON") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    return Observation.from_mapping(value)


def save_state(obs: Observation) -> None:
    validate_dir()
    fd, path = tempfile.mkstemp(prefix=".state-", dir=STATE_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump(obs.as_dict(), f, sort_keys=True, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(path, STATE_FILE)
        parent_fd = os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(path):
            os.unlink(path)


class PgController:
    def __init__(self, obs: Observation):
        self.obs = obs

    def _run(self, command: list[str], timeout: int = 20) -> str:
        # Never print command arguments or stderr: they can contain
        # operational metadata. The command has no passwords or URLs.
        try:
            p = subprocess.run(command, text=True, capture_output=True,
                               check=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Blocked("DOCKER_OR_PG_COMMAND_FAILED") from exc
        if len(p.stdout) > 1024:
            raise Blocked("UNEXPECTED_COMMAND_OUTPUT")
        return p.stdout.strip()

    def inspect(self) -> tuple[int, int]:
        cid = self.obs.container_id
        result = self._run([
            "docker", "inspect", "--format",
            "{{.Id}}|{{.State.Running}}|{{.HostConfig.LogConfig.Type}}|{{.LogPath}}", cid,
        ])
        pieces = result.split("|")
        if len(pieces) != 4 or pieces[0] != cid or pieces[1] != "true":
            raise Blocked("CONTAINER_IDENTITY_OR_STATE_CHANGED")
        if pieces[2] != "json-file":
            raise Blocked("LOG_DRIVER_CHANGED")
        path = Path(pieces[3])
        if not path.is_absolute() or not str(path).startswith("/var/lib/docker/containers/"):
            raise Blocked("UNEXPECTED_LOG_PATH")
        try:
            # O_NOFOLLOW prevents substituting a symlink for the Docker log.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise Blocked("LOG_NOT_REGULAR")
                size = st.st_size
            finally:
                os.close(fd)
            info = os.statvfs(path)
        except OSError as exc:
            raise Blocked("LOG_SIZE_OR_FREE_SPACE_UNAVAILABLE") from exc
        free = info.f_bavail * info.f_frsize
        return size, free

    def _psql(self, sql: str, readonly: bool) -> str:
        command = ["docker", "exec"]
        if readonly:
            command += ["-e", "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000"]
        command += [
            self.obs.container_id, "psql", "-X", "-qAt",
            "-v", "ON_ERROR_STOP=1", "-U", self.obs.role,
            "-d", self.obs.db, "-c", sql,
        ]
        return self._run(command)

    def state(self) -> tuple[str, str, bool]:
        result = self._psql(
            "SELECT setting || '|' || source || '|' || "
            "CASE WHEN pending_restart THEN 'true' ELSE 'false' END "
            "FROM pg_settings WHERE name='log_connections';",
            readonly=True,
        )
        pieces = result.split("|")
        if len(pieces) != 3 or pieces[0] not in ("on", "off") or pieces[2] not in ("true", "false"):
            raise Blocked("UNEXPECTED_GUC_STATE")
        return pieces[0], pieces[1], pieces[2] == "true"

    def reload(self) -> None:
        if self._psql("SELECT pg_reload_conf();", readonly=False) != "t":
            raise Blocked("PG_RELOAD_NOT_ACCEPTED")

    def restore(self) -> str:
        # An unverified or preexisting auto.conf baseline is forbidden in
        # Observation.from_mapping. RESET then reload must recover off.
        # Emergency SET off is a last-resort fail-safe if RESET fails.
        expected_source = "default" if self.obs.baseline_source == "default" else "configuration file"
        try:
            self._psql("ALTER SYSTEM RESET log_connections;", readonly=False)
            self.reload()
            value, source, restart = self.state()  # NEW session after reload
            if value == "off" and source == expected_source and not restart:
                return "RESTORED"
        except Blocked:
            pass

        # Do not claim the original source restored if it cannot be proved.
        # Explicitly force OFF while retaining phase='stopping' for retries.
        try:
            self._psql("ALTER SYSTEM SET log_connections = off;", readonly=False)
            self.reload()
            value, _, restart = self.state()
            if value == "off" and not restart:
                return "OFF_REQUIRES_SOURCE_RESTORE"
        except Blocked:
            pass
        return "STOP_RETRY_REQUIRED"


def tick(clock: int | None = None, controller_factory=PgController) -> str:
    obs = read_state()
    if obs.phase == "restored":
        return "RESTORED_ALREADY"
    controller = controller_factory(obs)
    try:
        log_size, disk_free = controller.inspect()
    except Blocked:
        # Cannot enforce cap or identity; attempt restore if the verified
        # container is still reachable. No success must be claimed.
        log_size, disk_free = -1, -1
    now = int(time.time()) if clock is None else clock
    action = "STOP" if log_size < 0 or disk_free < 0 else decide(obs, now, log_size, disk_free)
    if action == "WAIT":
        return "ARMED_MONITORING"
    if action == "DONE":
        return "RESTORED_ALREADY"
    if obs.phase != "stopping":
        save_state(replace(obs, phase="stopping"))
    result = controller.restore()
    if result == "RESTORED":
        save_state(replace(obs, phase="restored"))
        return "RESTORED_AND_VERIFIED"
    if result == "OFF_REQUIRES_SOURCE_RESTORE":
        raise Blocked("OFF_BUT_SOURCE_RESTORE_REQUIRED")
    raise Blocked("STOP_RETRY_REQUIRED")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "tick":
        print("SEC_HOST_A02_BLOCKED_TICK_ONLY", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("SEC_HOST_A02_BLOCKED_ROOT_REQUIRED", file=sys.stderr)
        return 1
    try:
        validate_dir()
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            lock_info = os.fstat(fd)
            if lock_info.st_uid != 0 or stat.S_IMODE(lock_info.st_mode) != 0o600:
                raise Blocked("LOCK_PERMISSIONS")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = tick()
            print("SEC_HOST_A02_WATCHDOG=" + result)
            return 0
        finally:
            os.close(fd)
    except (Blocked, OSError) as exc:
        # Sanitized exact codes; no Docker stderr, IP, role, path or SQL.
        code = str(exc) if isinstance(exc, Blocked) else "LOCK_OR_FS_ERROR"
        print("SEC_HOST_A02_WATCHDOG=BLOCKED_" + code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
