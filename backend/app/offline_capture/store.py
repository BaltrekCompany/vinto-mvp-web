"""Idempotent persistence contract of the offline capture receiver (OFF-04.4).

Contract (identical for every implementation):
  - `insert_received` is an atomic insert-if-absent keyed by `capture_id`; it reports whether THIS call inserted it.
    A concurrent insert of the same id waits for the other transaction and then reports "already present".
  - identity columns (author, device, form, machine, context, checksum, payload) are write-once;
  - `finalize` sets the result of a row exactly once, inside the transaction that inserted it, so a committed row is
    always final and its persisted response is reusable verbatim for retries;
  - rows are never deleted; every receipt decision is appended to an event log (never updated).
Implementations: PgOfflineCaptureStore (PostgreSQL, psycopg) and SqliteOfflineCaptureStore (tests that reproduce the
same transactional constraints). Nothing here touches the operational schema.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional, Protocol
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


class StoreUnavailable(Exception):
    """Temporary storage failure (maps to 503; nothing was committed)."""


@dataclass(frozen=True)
class NewReceipt:
    capture_id: UUID
    author_user_id: UUID
    device_key: UUID
    form_code: str
    form_version: int
    machine_code: str
    scope_snapshot_id: Optional[UUID]
    context_version: str
    payload_sha256: str
    payload: dict


@dataclass(frozen=True)
class Receipt:
    capture_id: UUID
    author_user_id: UUID
    device_key: UUID
    form_code: str
    form_version: int
    machine_code: str
    context_version: str
    payload_sha256: str
    outcome: str                      # received (only inside the inserting transaction) | accepted | accepted_warning | review | conflict
    reason: Optional[str]
    warnings: list
    server_seq: int
    response_status: Optional[int]
    response_body: Optional[dict]


class ReceiptTx(Protocol):
    def insert_received(self, receipt: NewReceipt) -> bool: ...
    def get(self, capture_id: UUID) -> Optional[Receipt]: ...
    def finalize(self, capture_id: UUID, *, outcome: str, reason: Optional[str], warnings: list, response_status: int, response_body: dict) -> None: ...
    def event(self, capture_id: UUID, kind: str, payload_sha256: Optional[str], author_user_id: Optional[UUID], detail: Optional[str]) -> None: ...


class OfflineCaptureStore(Protocol):
    def transaction(self) -> Any: ...       # context manager yielding a ReceiptTx; commit on exit, rollback on exception
    def get(self, capture_id: UUID) -> Optional[Receipt]: ...


# ----------------------------------------------------------------------------------------------- PostgreSQL
_COLS = "capture_id, author_user_id, device_key, form_code, form_version, machine_code, context_version, payload_sha256, outcome, reason, warnings, server_seq, response_status, response_body"


def _receipt_from(row: tuple) -> Receipt:
    cid, author, device, form, ver, machine, ctx, sha, outcome, reason, warnings, seq, status, body = row
    return Receipt(UUID(str(cid)), UUID(str(author)), UUID(str(device)), form, ver, machine, ctx, sha, outcome, reason,
                   list(warnings or []), int(seq), status, body)


class _PgTx:
    def __init__(self, connection) -> None:
        self.c = connection

    def insert_received(self, r: NewReceipt) -> bool:
        row = self.c.execute(
            "INSERT INTO vinto_offline.capture_receipt (capture_id, author_user_id, device_key, form_code, form_version, machine_code, scope_snapshot_id, "
            "context_version, payload_sha256, payload, outcome) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'received') "
            "ON CONFLICT (capture_id) DO NOTHING RETURNING capture_id",
            (r.capture_id, r.author_user_id, r.device_key, r.form_code, r.form_version, r.machine_code, r.scope_snapshot_id, r.context_version,
             r.payload_sha256, Jsonb(r.payload))).fetchone()
        return row is not None

    def get(self, capture_id: UUID) -> Optional[Receipt]:
        row = self.c.execute(f"SELECT {_COLS} FROM vinto_offline.capture_receipt WHERE capture_id = %s", (capture_id,)).fetchone()
        return _receipt_from(row) if row else None

    def finalize(self, capture_id, *, outcome, reason, warnings, response_status, response_body) -> None:
        n = self.c.execute(
            "UPDATE vinto_offline.capture_receipt SET outcome=%s, reason=%s, warnings=%s, response_status=%s, response_body=%s "
            "WHERE capture_id=%s AND outcome='received'", (outcome, reason, Jsonb(warnings), response_status, Jsonb(response_body), capture_id)).rowcount
        if n != 1:
            raise StoreUnavailable("finalize_without_received_row")

    def event(self, capture_id, kind, payload_sha256, author_user_id, detail) -> None:
        self.c.execute("INSERT INTO vinto_offline.capture_event (capture_id, kind, payload_sha256, author_user_id, detail) VALUES (%s,%s,%s,%s,%s)",
                       (capture_id, kind, payload_sha256, author_user_id, detail))


class PgOfflineCaptureStore:
    """`connect` returns a NEW psycopg connection (not autocommit) to a DISPOSABLE/test database (see db_guard)."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    @contextmanager
    def transaction(self) -> Iterator[_PgTx]:
        try:
            connection = self._connect()
        except psycopg.Error as error:
            raise StoreUnavailable(type(error).__name__) from None
        try:
            with connection:                       # COMMIT on success, ROLLBACK on exception
                yield _PgTx(connection)
        except psycopg.Error as error:
            raise StoreUnavailable(type(error).__name__) from None
        finally:
            connection.close()

    def get(self, capture_id: UUID) -> Optional[Receipt]:
        with self.transaction() as tx:
            return tx.get(capture_id)


# ----------------------------------------------------------------------------------------------- SQLite (tests)
SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS capture_receipt (
  capture_id TEXT PRIMARY KEY, author_user_id TEXT NOT NULL, device_key TEXT NOT NULL, form_code TEXT NOT NULL, form_version INTEGER NOT NULL,
  machine_code TEXT NOT NULL, scope_snapshot_id TEXT, context_version TEXT NOT NULL, payload_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
  outcome TEXT NOT NULL, reason TEXT, warnings TEXT NOT NULL DEFAULT '[]', server_seq INTEGER NOT NULL, response_status INTEGER, response_body TEXT,
  received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capture_event (id INTEGER PRIMARY KEY AUTOINCREMENT, capture_id TEXT NOT NULL, kind TEXT NOT NULL, payload_sha256 TEXT,
  author_user_id TEXT, detail TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seq (id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL);
INSERT OR IGNORE INTO seq (id, n) VALUES (1, 0);
"""


class _SqliteTx:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.c = connection

    def insert_received(self, r: NewReceipt) -> bool:
        if self.c.execute("SELECT 1 FROM capture_receipt WHERE capture_id=?", (str(r.capture_id),)).fetchone():
            return False
        self.c.execute("UPDATE seq SET n = n + 1 WHERE id = 1")
        seq = self.c.execute("SELECT n FROM seq WHERE id = 1").fetchone()[0]
        self.c.execute("INSERT INTO capture_receipt (capture_id, author_user_id, device_key, form_code, form_version, machine_code, scope_snapshot_id, "
                       "context_version, payload_sha256, payload, outcome, server_seq, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,'received',?,?)",
                       (str(r.capture_id), str(r.author_user_id), str(r.device_key), r.form_code, r.form_version, r.machine_code,
                        str(r.scope_snapshot_id) if r.scope_snapshot_id else None, r.context_version, r.payload_sha256,
                        json.dumps(r.payload, ensure_ascii=False), seq, datetime.now(timezone.utc).isoformat()))
        return True

    def get(self, capture_id: UUID) -> Optional[Receipt]:
        row = self.c.execute("SELECT capture_id, author_user_id, device_key, form_code, form_version, machine_code, context_version, payload_sha256, outcome, "
                             "reason, warnings, server_seq, response_status, response_body FROM capture_receipt WHERE capture_id=?", (str(capture_id),)).fetchone()
        if not row:
            return None
        return _receipt_from((*row[:10], json.loads(row[10]), row[11], row[12], json.loads(row[13]) if row[13] else None))

    def finalize(self, capture_id, *, outcome, reason, warnings, response_status, response_body) -> None:
        n = self.c.execute("UPDATE capture_receipt SET outcome=?, reason=?, warnings=?, response_status=?, response_body=? WHERE capture_id=? AND outcome='received'",
                           (outcome, reason, json.dumps(warnings), response_status, json.dumps(response_body), str(capture_id))).rowcount
        if n != 1:
            raise StoreUnavailable("finalize_without_received_row")

    def event(self, capture_id, kind, payload_sha256, author_user_id, detail) -> None:
        self.c.execute("INSERT INTO capture_event (capture_id, kind, payload_sha256, author_user_id, detail, at) VALUES (?,?,?,?,?,?)",
                       (str(capture_id), kind, payload_sha256, str(author_user_id) if author_user_id else None, detail, datetime.now(timezone.utc).isoformat()))


class SqliteOfflineCaptureStore:
    """File- or memory-backed store with the same contract. Writers are serialised with BEGIN IMMEDIATE (one writer at a time)."""
    _lock = threading.Lock()

    def __init__(self, path: str) -> None:
        self.path = path
        self._keep = None
        if path == ":memory:":                      # one shared connection for memory databases
            self._keep = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._keep.executescript(SQLITE_DDL)
        else:
            with self._open() as c:
                c.executescript(SQLITE_DDL)

    def _open(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        return c

    @contextmanager
    def transaction(self) -> Iterator[_SqliteTx]:
        c = self._keep or self._open()
        guard = self._lock if self._keep else None
        if guard:
            guard.acquire()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield _SqliteTx(c)
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
        except sqlite3.Error as error:
            raise StoreUnavailable(type(error).__name__) from None
        finally:
            if guard:
                guard.release()
            if not self._keep:
                c.close()

    def get(self, capture_id: UUID) -> Optional[Receipt]:
        with self.transaction() as tx:
            return tx.get(capture_id)

    # test helpers (read only)
    def counts(self) -> dict:
        with self.transaction() as tx:
            cur = tx.c
            return {"receipts": cur.execute("SELECT count(*) FROM capture_receipt").fetchone()[0],
                    "events": cur.execute("SELECT count(*) FROM capture_event").fetchone()[0]}
